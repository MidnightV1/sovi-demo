from __future__ import annotations
from typing import List, Dict, Any, Optional
from datetime import datetime


class MessageBuilder:
    """消息构建器：在客户端外部构造历史与当前消息。
    - 不访问数据库；history 由上层传入
    - 支持历史消息、时间/画像块、当前用户输入（system prompt 由上层配置传入，不作为一条消息）
    - 历史消息若包含 image_url，将透传给传输层由其拉取二进制并生成图片 Part
    """

    def build_conversation_messages(
        self,
        user_input: str,
        history: Optional[List[Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None,
        image_data: Optional[bytes] = None,
        client_datetime: Optional[str] = None,
        client_language: Optional[str] = None,
        client_timezone_offset: Optional[int] = None,
        user_profile: Optional[str] = None,
        is_new_conversation: bool = False,
    user_refer_text: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        messages: List[Dict[str, Any]] = []

        # 1) 为兼容现有单元测试，将 system prompt 也保留为首条 system 消息；
        #    实际传输仍由上层通过 generation_config.system_instruction 注入，传输层会忽略该条。
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        # 2) history（按 round_num 排序；若存在欢迎消息则前插 session start）
        if history:
            has_welcome = any(
                (h.get('role') == 'server' and h.get('round_num') in (0, '0')) for h in history
            )
            if has_welcome:
                messages.append({'role': 'user', 'content': 'session start'})

            sorted_history = sorted(history, key=lambda x: x.get('round_num', 0))
            for h in sorted_history:
                msg: Dict[str, Any] = {
                    'role': h.get('role', 'user'),
                    'content': (
                        h.get('working_content')
                        or h.get('view_content')
                        or h.get('origin_content')
                        or h.get('content')
                        or ''
                    )
                }
                # 透传历史图片 URL，交由传输层加载为图片 Part
                if h.get('image_url'):
                    msg['image_url'] = h.get('image_url')
                messages.append(msg)

        # 3) 当前消息
        # 3) 构造与旧版一致的包装（时间/画像/标记）
        def _format_client_time(dt_val: Optional[object]) -> Optional[str]:
            """将输入时间规范化为 'YYYY-MM-DD HH:MM' 字符串。
            - 支持 datetime 对象或字符串（ISO/常见格式）
            - 失败时返回原始去空白字符串（尽量裁剪到前16位），若为空返回 None
            """
            if dt_val is None:
                return None
            try:
                if isinstance(dt_val, datetime):
                    return dt_val.strftime('%Y-%m-%d %H:%M')
                s = str(dt_val).strip()
                if not s:
                    return None
                # 常见清洗：替换T/去Z
                s2 = s.replace('T', ' ').replace('Z', '').strip()
                # 直接尝试几种格式
                for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y/%m/%d %H:%M:%S', '%Y/%m/%d %H:%M'):
                    try:
                        return datetime.strptime(s2, fmt).strftime('%Y-%m-%d %H:%M')
                    except Exception:
                        pass
                # 尝试 fromisoformat（可能包含秒）
                try:
                    return datetime.fromisoformat(s2).strftime('%Y-%m-%d %H:%M')
                except Exception:
                    pass
                # 兜底：若形如 YYYY-MM-DD HH:MM[:SS]，裁到前16位
                if len(s2) >= 16 and s2[4] == '-' and s2[7] == '-' and s2[10] == ' ' and s2[13] == ':':
                    return s2[:16]
                return s2  # 最后兜底，返回清洗后的原文
            except Exception:
                return None

        def _build_datetime_block(dt: Optional[object], tz_offset_min: Optional[int]) -> str:
            fmt = _format_client_time(dt)
            if not fmt and tz_offset_min is not None:
                try:
                    from datetime import datetime, timezone, timedelta
                    # 使用 UTC 当前时间 + 偏移分钟 生成用户本地时间
                    local_now = datetime.now(timezone.utc) + timedelta(minutes=int(tz_offset_min))
                    fmt = local_now.strftime('%Y-%m-%d %H:%M')
                except Exception:
                    fmt = None
            return f"# User's Current Date and Time\n{fmt}\n\n" if fmt else ""

        def _build_user_profile_block(profile: Optional[str]) -> str:
            """构建用户画像块（遵循旧实现与新规则）
            规则：
            - 非空字符串 → 标题 + 原文
            - False / None / 空字符串 → 标题 + 默认文案
            - 构造异常 → 返回空串（整块为空）
            """
            try:
                # 非空字符串
                if isinstance(profile, str) and profile.strip():
                    return f"# What You Know About the User\n{profile.strip()}\n\n"
                # False（查询失败）与 None/空字符串：使用默认文案
                if profile is False or not profile or not str(profile).strip():
                    return "# What You Know About the User\nYou don't know anything about the user.\n\n"
                # 其他类型兜底：尝试转字符串后再判断
                s = str(profile).strip()
                if s:
                    return f"# What You Know About the User\n{s}\n\n"
                return "# What You Know About the User\nYou don't know anything about the user.\n\n"
            except Exception:
                # 异常 → 整块为空
                return ""

        # 基于入参与时区偏移构造时间/画像块
        datetime_block = _build_datetime_block(client_datetime, client_timezone_offset)
        profile_block = _build_user_profile_block(user_profile)
        # 构造引用块（仅当提供时加入）
        user_refer_block = (
            "## base on the past conversation, this reference in the user selected text\n"
            f"<|user_refer_begin|>{(user_refer_text or '').strip()}<|user_refer_end|>\n\n"
        ) if (isinstance(user_refer_text, str) and user_refer_text.strip()) else ""
        user_text = (user_input or "").strip()

        # 按旧版语义：消息体仅包含用户原始文本；时间与画像块通过 meta 传递，由传输层拼接并加标签
        current_message: Dict[str, Any] = {"role": "user", "content": user_text}
        if image_data:
            # 保留实际的图片数据，由GoogleTransport处理
            current_message["image_data"] = image_data

        # 传递元信息，便于传输层做与旧版一致的包装
        current_message["meta"] = {
            "is_new_conversation": bool(is_new_conversation),
            "client_datetime": client_datetime,
            "client_language": client_language,
            "client_timezone_offset": client_timezone_offset,
            "user_profile": user_profile,
            # 直接传递已构建的块文本，避免传输层重复判定
            "blocks": {
                "datetime": datetime_block,
                "profile": profile_block,
                "user_refer": user_refer_block,
            },
        }

        messages.append(current_message)

        return messages

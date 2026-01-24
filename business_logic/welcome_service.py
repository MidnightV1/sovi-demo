from __future__ import annotations
from typing import Optional, Generator
import json
from datetime import datetime, timezone, timedelta

from business_logic.transaction_manager import TransactionManager
from business_logic.response_parser import ResponseParser
from prompts.system_prompts import SystemPrompts


class WelcomeService:
    """
    轻量欢迎流服务：
    - 通过遗留 gemini 生成欢迎内容并保存为独立消息（round_num = -1, role = server）
    - 与现有主流一致，仅转发 <Sovi_Response_Msg> 片段
    """

    def __init__(self, *, db, gemini_client, tx_manager: TransactionManager, response_parser: ResponseParser, system_cache_mgr: object | None = None):
        self._db = db
        self._gemini = gemini_client
        self._tx = tx_manager
        self._parser = response_parser
        self._cache_mgr = system_cache_mgr

    def stream_welcome(self, user_id: int, client_datetime: Optional[str], client_language: Optional[str], client_timezone_offset: Optional[int] = None) -> Generator[str, None, None]:
        # 先发成功信号（与现实现一致）
        yield f"data: {json.dumps({'success': True, 'new_welcome': True})}\n\n"

        # 初始化流状态与度量
        full_response = ""
        final_chunk = None
        req_start = datetime.utcnow()
        first_token_time = None
        user_visible_time = None
        last_message_info = ''

        # 流式传输时按增量裁剪 <Sovi_Response_Msg>
        start_tag = '<Sovi_Response_Msg>'
        end_tag = '</Sovi_Response_Msg>'
        streaming_started = False
        streaming_finished = False
        sent_length = 0

        try:
            # 用户画像与上次消息时间
            user_profile = self._db.get_active_user_profile(user_id)
            last_message_time = self._db.get_user_last_message_time(user_id)
            if last_message_time:
                # 统一格式：'YYYY-MM-DD HH:MM'，优先使用客户端时区偏移
                try:
                    dt = last_message_time
                    # 允许 DB 返回 str 或 datetime
                    if isinstance(dt, str):
                        s = dt.strip().replace('T', ' ')
                        try:
                            # 优先 fromisoformat（支持 +00:00）
                            dt_obj = datetime.fromisoformat(s)
                        except Exception:
                            # 常见格式兜底
                            for fmt in ('%Y-%m-%d %H:%M:%S.%f%z', '%Y-%m-%d %H:%M:%S%z', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
                                try:
                                    dt_obj = datetime.strptime(s, fmt)
                                    break
                                except Exception:
                                    dt_obj = None
                            if dt_obj is None:
                                dt_obj = None
                    else:
                        dt_obj = dt

                    fmt_str = None
                    if dt_obj:
                        # 归一到 UTC 再应用客户端偏移分钟
                        try:
                            # 若无 tzinfo，按 UTC 处理
                            if getattr(dt_obj, 'tzinfo', None) is None:
                                dt_utc = dt_obj.replace(tzinfo=timezone.utc)
                            else:
                                # 转成 UTC
                                dt_utc = dt_obj.astimezone(timezone.utc)
                            if client_timezone_offset is not None:
                                dt_local = dt_utc + timedelta(minutes=int(client_timezone_offset))
                            else:
                                dt_local = dt_utc
                            fmt_str = dt_local.strftime('%Y-%m-%d %H:%M')
                        except Exception:
                            fmt_str = None

                    if fmt_str:
                        last_message_info = f"Last seen: {fmt_str}"
                    else:
                        # 无法解析则留空，避免把微秒/时区原样带入
                        last_message_info = ''
                except Exception:
                    last_message_info = ''

            request_payload_for_log = {
                'model': getattr(self._gemini, "_model_name", "gemini-2.0-flash-exp"),
                'has_image': False,
                'config': {
                    'max_output_tokens': 2048,
                    'temperature': 0.5,
                    'thinking_config': {
                        'thinking_budget': 0,
                        'include_thoughts': False,
                    }
                }
            }

            # 流式生成（使用新客户端 from_raw 接口）
            # 系统指令使用主 Prompt，命令体作为当前轮用户文本进入 <|server_command_begin|> 内
            welcome_system_prompt = SystemPrompts.get_main_prompt()
            # 尝试为欢迎流的系统prompt启用缓存（与主对话一致）
            model_name = getattr(self._gemini, "_model_name", "gemini-2.0-flash-exp")
            cache_name = None
            if self._cache_mgr is not None:
                try:
                    cache_name = self._cache_mgr.get_or_create_system_cache(model_name, welcome_system_prompt)
                except Exception:
                    cache_name = None
            welcome_command_text = SystemPrompts.get_welcome_generation_command(
                client_language=(client_language or "EN"),
                last_message_info=last_message_info,
                user_profile=user_profile,
            )
            # 若未提供客户端时间，按时区偏移计算本地当前时间
            effective_client_time = client_datetime
            if not effective_client_time and client_timezone_offset is not None:
                try:
                    effective_client_time = (datetime.now(timezone.utc) + timedelta(minutes=int(client_timezone_offset))).strftime('%Y-%m-%d %H:%M')
                except Exception:
                    effective_client_time = client_datetime

            from api_clients.gemini_client import ModelConfig
            model_cfg = ModelConfig()
            if cache_name:
                model_cfg.cached_content = cache_name

            for event in self._gemini.chat_with_streaming_from_raw(
                user_input=welcome_command_text,
                history=[],
                system_prompt=welcome_system_prompt,
                image_data=None,
                client_datetime=effective_client_time,
                client_language=client_language,
                client_timezone_offset=client_timezone_offset,
                user_profile=user_profile,
                is_new_conversation=True,
                model_config=model_cfg,
                client_request_id=f"welcome_{user_id}",
            ):
                # 处理标准化事件
                text = ''
                if isinstance(event, dict):
                    etype = event.get('type')
                    if etype == 'stream_chunk':
                        if event.get('_raw') is not None:
                            final_chunk = event.get('_raw')
                        text = event.get('text') or ''
                    elif etype == 'completion':
                        if event.get('_final_raw') is not None:
                            final_chunk = event.get('_final_raw')
                        if not full_response:
                            full_response = event.get('raw_response') or full_response
                        text = ''
                else:
                    final_chunk = event
                    text = getattr(event, 'text', '') or (event if isinstance(event, str) else '')

                # 捕获完成事件中的请求payload（优先使用 contents 版本）
                if isinstance(event, dict) and event.get('type') == 'completion':
                    if event.get('request_payload_full'):
                        request_payload_for_log = event.get('request_payload_full')
                    elif event.get('request_payload'):
                        request_payload_for_log = event.get('request_payload')

                # 首 token 到达时间：第一段可见文本即记录
                if first_token_time is None and text:
                    first_token_time = datetime.utcnow()
                # 若启用缓存，但尚未收到完成事件，确保兜底payload体现cached_content且不含system
                try:
                    if cache_name and isinstance(request_payload_for_log, dict):
                        cfg = request_payload_for_log.setdefault('config', {})
                        cfg.setdefault('max_output_tokens', 2048)
                        cfg.setdefault('temperature', 0.2)
                        cfg.setdefault('thinking_config', {'thinking_budget': 0, 'include_thoughts': False})
                        cfg['cached_content'] = cache_name
                        if 'system_instruction' in request_payload_for_log:
                            request_payload_for_log.pop('system_instruction', None)
                except Exception:
                    pass

                if not text:
                    continue

                full_response += text

                if not streaming_finished:
                    if not streaming_started and start_tag in full_response:
                        streaming_started = True
                        # 用户可见首 token：检测到开始标签首次出现时记录
                        if user_visible_time is None:
                            user_visible_time = datetime.utcnow()
                        sent_length = 0
                    if streaming_started:
                        start_pos = full_response.find(start_tag) + len(start_tag)
                        body = full_response[start_pos:]

                        # 是否出现结束标签
                        end_pos = body.find(end_tag)
                        if end_pos != -1:
                            # 找到结束标签：本次允许发送至 end_pos，且不包含标签本身
                            to_send_upto = end_pos
                            streaming_finished = True
                        else:
                            # 未结束：保留尾部 end_tag_len+5 字符，避免分片标签泄露
                            holdback = max(0, len(end_tag) + 5)
                            to_send_upto = max(0, len(body) - holdback)

                        # 仅发送未发送的新内容
                        if to_send_upto > sent_length:
                            new_content = body[sent_length:to_send_upto]
                            if new_content:
                                yield f"data: {json.dumps({'type': 'chunk', 'content': new_content})}\n\n"
                                sent_length = to_send_upto

            # 完成后保存独立欢迎消息
            if not streaming_started:
                # 告警：未找到开始标签
                yield f"data: {json.dumps({'type': 'warning', 'message': '警告：完整响应未找到开始标签 <Sovi_Response_Msg>'})}\n\n"

            parsed = self._parser.parse_xml_response(full_response)
            content = (parsed.get('display_content') or full_response)
            if content.startswith('\n'):
                content = content.lstrip('\n')
            if content.endswith('\n'):
                content = content.rstrip('\n')

            # 计算毫秒耗时（与旧版一致，user_visible 为空则回退首 token）
            if user_visible_time is None:
                user_visible_time = first_token_time
            ft_ms = int((first_token_time - req_start).total_seconds() * 1000) if first_token_time else None
            uv_ms = int((user_visible_time - req_start).total_seconds() * 1000) if user_visible_time else None

            with self._tx.begin() as _:
                # 1) 保存API请求日志
                self._tx.save_api_request_log(
                    user_id=user_id,
                    conversation_id=None,
                    message_id=None,
                    model_name=getattr(self._gemini, "_model_name", "gemini-2.0-flash-exp"),
                    request_data=request_payload_for_log,
                    raw_response=full_response,
                    full_response=full_response,
                    final_chunk=final_chunk,
                    request_start_time=req_start,
                    first_token_time_ms=ft_ms,
                    user_visible_time_ms=uv_ms,
                    completion_time=datetime.utcnow(),
                    status='success',
                    session_context='welcome_generation',
                    request_type='gemini_welcome',
                    has_current_image=False,
                    used_cache=bool(cache_name),
                    cache_name=cache_name or None,
                    cached_tokens=(
                        getattr(getattr(final_chunk, 'usage_metadata', None), 'cached_content_token_count', None)
                        if final_chunk is not None else None
                    ),
                )
                # 2) 保存欢迎消息（独立消息，无会话ID）
                self._db.save_message(
                    conversation_id=None,
                    user_id=user_id,
                    role='server',
                    round_num=-1,
                    origin_content=parsed.get('raw_response', content),
                    view_content=content,
                    working_content=parsed.get('working_content'),
                    content_summary=parsed.get('content_summary'),
                    action_mode=parsed.get('action_mode'),
                    question_meta=None,
                    is_valid_question=parsed.get('is_valid_question'),
                    image_url=None,
                    api_request_id=None,
                    send_status='success',
                )

            yield f"data: {json.dumps({'type': 'complete'})}\n\n"
        except Exception as e:
            # 失败也落库
            try:
                # 计算毫秒耗时（失败场景同样写入）
                if user_visible_time is None:
                    user_visible_time = first_token_time
                ft_ms = int((first_token_time - req_start).total_seconds() * 1000) if first_token_time else None
                uv_ms = int((user_visible_time - req_start).total_seconds() * 1000) if user_visible_time else None
                self._tx.save_api_request_log(
                    user_id=user_id,
                    conversation_id=None,
                    message_id=None,
                    model_name=getattr(self._gemini, "_model_name", "gemini-2.0-flash-exp"),
                    request_data={
                        'model': getattr(self._gemini, "_model_name", "gemini-2.0-flash-exp"),
                        'user_input': '[Welcome]'+(last_message_info or ''),
                        'has_image': False,
                        'config': {
                            'max_output_tokens': 2048,
                            'temperature': 0.2,
                            'thinking_config': {'thinking_budget': 0, 'include_thoughts': False},
                            **({'cached_content': cache_name} if 'cache_name' in locals() and cache_name else {})
                        }
                        # 使用缓存时不要记录system_instruction
                    },
                    raw_response=str(e),
                    full_response=full_response,
                    final_chunk=None,
                    request_start_time=req_start,
                    first_token_time_ms=ft_ms,
                    user_visible_time_ms=uv_ms,
                    completion_time=datetime.utcnow(),
                    status='error',
                    error_message='欢迎消息生成失败',
                    session_context='welcome_generation',
                    request_type='gemini_welcome',
                    has_current_image=False,
                    used_cache=bool(cache_name) if 'cache_name' in locals() else None,
                    cache_name=cache_name if ('cache_name' in locals() and cache_name) else None,
                )
            except Exception:
                pass
            yield f"data: {json.dumps({'type': 'error', 'message': '欢迎消息生成失败'})}\n\n"

from __future__ import annotations
from typing import Generator, Dict, Any, Optional
import json
import time
from datetime import datetime

from business_logic.transaction_manager import TransactionManager
from business_logic.message_status_service import MessageStatusService
from business_logic.session_meta_service import SessionMetaService
from business_logic.profile_service import ProfileService
from business_logic.response_parser import ResponseParser
from business_logic.exceptions import XmlParseError
from api_clients.message_builder import MessageBuilder
from prompts.system_prompts import SystemPrompts


class ChatOrchestrator:
    """
    业务编排器：保持遗留 gemini_client 行为不变的前提下，增加状态机与短事务提交。
    - 仍由遗留 gemini_client 负责：消息构造/系统提示/图片容错/缓存/成本/日志与XML解析函数。
    - 这里仅负责：
      1) 写入用户消息为pending
      2) 流式转发SSE，按 <Sovi_Response_Msg> 裁剪
      3) 结束后解析 + 短事务一次性保存AI消息/元数据/标题/画像
      4) 将用户消息标记success；异常则failed
    """

    def __init__(self, *, db, gemini_client, response_parser: ResponseParser,
                 tx_manager: TransactionManager,
                 msg_service: MessageStatusService,
                 session_meta_svc: SessionMetaService,
                 profile_svc: ProfileService,
                 system_cache_mgr: object | None = None):
        self._db = db
        self._gemini = gemini_client
        self._parser = response_parser
        self._tx = tx_manager
        self._msg_svc = msg_service
        self._session_svc = session_meta_svc
        self._profile_svc = profile_svc
        self._cache_mgr = system_cache_mgr

    def stream_chat(
        self,
        *,
        user_id: int,
        conversation_id: int,
        user_text: str,
    user_refer_text: Optional[str] = None,
        round_num: int,
        image_path: Optional[str],
        client_datetime: Optional[str],
    client_language: Optional[str],
    client_timezone_offset: Optional[int] = None,
    ) -> Generator[str, None, None]:
        # 幂等/阶段标记：用于避免成功后因SSE写出异常再次记error日志或反转状态
        request_logged = False
        success_committed = False
        # 记录请求开始时间与延迟指标（对齐旧版）
        req_start_time = datetime.utcnow()
        first_token_time = None
        user_visible_time = None

        # 1) 先入库用户消息为 pending
        user_msg = self._msg_svc.create_pending_user_message(
            conversation_id=conversation_id,
            user_id=user_id,
            content=user_text,
            round_num=round_num,
            image_path=image_path,
        )
        user_message_id = user_msg['message_id']

        # 2) 获取画像与历史（业务层负责，只读，不让API层碰DB）
        user_profile = self._db.get_active_user_profile(user_id)
        history: list[dict] = []
        try:
            raw_history = self._db.get_conversation_history(conversation_id, limit=20)
            history = [h for h in (raw_history or []) if h.get('message_id') != user_message_id]
        except Exception:
            history = []

        # 3) 准备流裁剪状态
        start_tag = "<Sovi_Response_Msg>"
        end_tag = "</Sovi_Response_Msg>"
        end_tag_len = len(end_tag)
        full_response = ""
        streaming_started = False
        streaming_finished = False
        # 已向前端发送的“正文长度”（不包含为防止标签分片而保留的尾部）
        sent_length = 0
        last_heartbeat = time.time()
        heartbeat_interval = 30
        final_chunk = None  # 底层chunk
        # 系统 Prompt 与（可选）缓存
        system_prompt = SystemPrompts.get_main_prompt()
        model_name = getattr(self._gemini, "_model_name", "gemini-2.0-flash-exp")
        cache_name: str | None = None
        if self._cache_mgr is not None:
            try:
                cache_name = self._cache_mgr.get_or_create_system_cache(model_name, system_prompt)
            except Exception:
                cache_name = None

        # 预构造一个结构化 request payload（即使异常也能记录完整请求），以 contents 为准
        request_payload_for_log: Dict[str, Any] = self._prebuild_request_payload(
            user_text=user_text,
            user_refer_text=user_refer_text,
            history=history,
            image_bytes=(None if not image_path else self._safe_read_image(image_path)),
            client_datetime=client_datetime,
            client_language=client_language,
            client_timezone_offset=client_timezone_offset,
            user_profile=user_profile,
            is_new_conversation=(round_num == 1),
        )
        # 为 has_current_image 推断提供直接标志，便于日志层快速识别
        try:
            if isinstance(request_payload_for_log, dict):
                has_img_flag = bool(image_path)
                # 在 contents 已包含 inline_data 情况下也可被 _infer_has_image_from_request 识别，这里做显式冗余标记
                request_payload_for_log['has_image'] = has_img_flag
        except Exception:
            pass
        # 若已确定将使用缓存，则让兜底payload也与实际一致：加入config.cached_content并移除system_instruction
        try:
            if cache_name:
                if not isinstance(request_payload_for_log.get('config'), dict):
                    request_payload_for_log['config'] = {
                        'max_output_tokens': 2048,
                        'temperature': 0.2,
                        'thinking_config': {
                            'thinking_budget': 0,
                            'include_thoughts': False,
                        }
                    }
                request_payload_for_log['config']['cached_content'] = cache_name
                # 日志兜底与发送感知一致：使用缓存时不记录 system_instruction
                if 'system_instruction' in request_payload_for_log:
                    request_payload_for_log.pop('system_instruction', None)
        except Exception:
            pass

        try:
            # 使用新客户端发起流（仅主对话对system prompt启用缓存；欢迎流不使用缓存）
            from api_clients.gemini_client import ModelConfig
            model_cfg = ModelConfig()
            if cache_name:
                model_cfg.cached_content = cache_name
            
            # 时间戳: Gemini API调用开始
            gemini_start_time = datetime.now()
            print(f"[PERF][{user_id}_{user_message_id}] Gemini API call started: {gemini_start_time.isoformat()}")
            
            first_chunk_received = False
            for event in self._gemini.chat_with_streaming_from_raw(
                user_input=user_text,
                history=history,
                system_prompt=system_prompt,
                image_data=(None if not image_path else self._safe_read_image(image_path)),
                client_datetime=client_datetime,
                client_language=client_language,
                client_timezone_offset=client_timezone_offset,
                user_profile=user_profile,
                is_new_conversation=(round_num == 1),
                model_config=model_cfg,
                client_request_id=f"{user_id}_{user_message_id}",
                user_refer_text=user_refer_text,
            ):
                # 时间戳: Gemini首次响应
                if not first_chunk_received:
                    gemini_first_response_time = datetime.now()
                    print(f"[PERF][{user_id}_{user_message_id}] Gemini first response: {gemini_first_response_time.isoformat()}")
                    first_chunk_received = True
                # 标准事件处理
                text = ""
                if isinstance(event, dict):
                    etype = event.get('type')
                    if etype == 'stream_chunk':
                        if event.get('_raw') is not None:
                            final_chunk = event.get('_raw')
                        text = event.get('text') or ""
                    elif etype == 'completion':
                        if event.get('_final_raw') is not None:
                            final_chunk = event.get('_final_raw')
                        if not full_response:
                            full_response = event.get('raw_response') or full_response
                        text = ""
                else:
                    final_chunk = event
                    if hasattr(event, 'text') and event.text:
                        text = event.text
                    elif isinstance(event, str):
                        text = event

                # 心跳
                now = time.time()
                if now - last_heartbeat > heartbeat_interval:
                    yield f": heartbeat\n\n"
                    last_heartbeat = now

                # 首token时间：第一段可见文本到达即记录
                if first_token_time is None and text:
                    first_token_time = datetime.utcnow()

                # 接收完成事件中的完整请求payload（优先使用 full 版本）
                if isinstance(event, dict) and event.get('type') == 'completion':
                    if event.get('request_payload_full'):
                        request_payload_for_log = event.get('request_payload_full')
                    elif event.get('request_payload'):
                        # 兼容旧字段（可能包含截断），仅作为兜底
                        request_payload_for_log = event.get('request_payload')

                if not text:
                    continue
                full_response += text

                if not streaming_finished:
                    # 尚未开始：寻找开始标签
                    if not streaming_started and start_tag in full_response:
                        streaming_started = True
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
                            holdback = max(0, end_tag_len + 5)
                            to_send_upto = max(0, len(body) - holdback)

                        # 仅发送未发送的新内容
                        if to_send_upto > sent_length:
                            new_content = body[sent_length:to_send_upto]
                            if new_content:
                                yield f"data: {json.dumps({'type': 'chunk', 'content': new_content})}\n\n"
                                sent_length = to_send_upto

            # 结束后解析与入库
            if not streaming_started:
                yield f"data: {json.dumps({'type': 'warning', 'message': '警告：完整响应未找到开始标签 <Sovi_Response_Msg>'})}\n\n"
            elif not streaming_finished:
                # 开始标签存在但未检测到结束标签：为避免泄露分片的结束标签，最后的少量尾部被安全丢弃
                yield f"data: {json.dumps({'type': 'warning', 'message': '警告：未检测到结束标签 </Sovi_Response_Msg>，尾部已安全裁剪'})}\n\n"

            parsed = self._parser.parse_xml_response(full_response)
            display_content = parsed.get('display_content', full_response)
            if display_content.startswith('\n'):
                display_content = display_content.lstrip('\n')
            if display_content.endswith('\n'):
                display_content = display_content.rstrip('\n')

            # 计算延迟毫秒（对齐旧逻辑：user_visible_time 为空则回退到 first_token_time）
            if user_visible_time is None:
                user_visible_time = first_token_time
            ft_ms = int((first_token_time - req_start_time).total_seconds() * 1000) if first_token_time else None
            uv_ms = int((user_visible_time - req_start_time).total_seconds() * 1000) if user_visible_time else None

            with self._tx.begin() as _:
                api_request_id = self._tx.save_api_request_log(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    message_id=user_message_id,
                    model_name=getattr(self._gemini, "_model_name", "gemini-2.0-flash-exp"),
                    request_data=request_payload_for_log,
                    raw_response=full_response,
                    full_response=full_response,
                    final_chunk=final_chunk,
                    request_start_time=req_start_time,
                    first_token_time_ms=ft_ms,
                    user_visible_time_ms=uv_ms,
                    completion_time=datetime.utcnow(),
                    used_cache=bool(cache_name),
                    cache_name=cache_name or None,
                    cached_tokens=(
                        getattr(getattr(final_chunk, 'usage_metadata', None), 'cached_content_token_count', None)
                        if final_chunk is not None else None
                    ),
                )
                request_logged = True

                self._db.save_message(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    role='assistant',
                    round_num=round_num,
                    origin_content=parsed.get('raw_response', display_content),
                    view_content=display_content,
                    working_content=parsed.get('working_content'),
                    content_summary=parsed.get('content_summary'),
                    action_mode=parsed.get('action_mode'),
                    question_meta=parsed.get('question_meta_xml') or parsed.get('question_meta'),
                    is_valid_question=parsed.get('is_valid_question'),
                    image_url=None,
                    api_request_id=api_request_id,
                    send_status='success',
                )
                self._session_svc.update_title_if_needed(conversation_id, parsed.get('session_meta'))
                self._profile_svc.save_if_needed(user_id, parsed.get('profile_update'))

            self._msg_svc.finalize_success(user_message_id)
            success_committed = True
            
            # 时间戳: 业务处理完成（数据库保存完成）
            business_complete_time = datetime.now()
            print(f"[PERF][{user_id}_{user_message_id}] Business complete: {business_complete_time.isoformat()}")
            
            # 确保可序列化：使用 to_dict()
            try:
                payload = {
                    'type': 'complete',
                    'conversation_id': conversation_id,
                    'parsed_response': (parsed.to_dict() if hasattr(parsed, 'to_dict') else parsed),
                }
                yield f"data: {json.dumps(payload)}\n\n"
            except Exception:
                # 避免在业务已成功提交后，再触发最外层异常导致重复写入error日志
                # 仅记录并结束生成器
                import logging
                logging.getLogger(__name__).warning('SSE complete payload write failed after success; suppressed')
                return

        except XmlParseError as xe:
            # 若已成功落库并完成状态，则不再写入error日志/反转状态
            if not success_committed:
                try:
                    # 计算已采集的时间指标
                    if user_visible_time is None:
                        user_visible_time = first_token_time
                    ft_ms = int((first_token_time - req_start_time).total_seconds() * 1000) if first_token_time else None
                    uv_ms = int((user_visible_time - req_start_time).total_seconds() * 1000) if user_visible_time else None
                    self._tx.save_api_request_log(
                        user_id=user_id,
                        conversation_id=conversation_id,
                        message_id=user_message_id,
                        model_name=getattr(self._gemini, "_model_name", "gemini-2.0-flash-exp"),
                        request_data=request_payload_for_log,
                        raw_response=full_response,
                        full_response=full_response,
                        final_chunk=None,
                        request_start_time=req_start_time,
                        first_token_time_ms=ft_ms,
                        user_visible_time_ms=uv_ms,
                        completion_time=datetime.utcnow(),
                        status='error',
                        error_message=str(xe),
                    )
                except Exception:
                    pass
                self._msg_svc.mark_failed(user_message_id)
            yield f"data: {json.dumps({'type': 'error', 'message': str(xe)})}\n\n"
        except Exception as e:
            if not success_committed:
                try:
                    if user_visible_time is None:
                        user_visible_time = first_token_time
                    ft_ms = int((first_token_time - req_start_time).total_seconds() * 1000) if first_token_time else None
                    uv_ms = int((user_visible_time - req_start_time).total_seconds() * 1000) if user_visible_time else None
                    self._tx.save_api_request_log(
                        user_id=user_id,
                        conversation_id=conversation_id,
                        message_id=user_message_id,
                        model_name=getattr(self._gemini, "_model_name", "gemini-2.0-flash-exp"),
                        request_data=request_payload_for_log,
                        raw_response=str(e),
                        full_response=full_response,
                        final_chunk=None,
                        request_start_time=req_start_time,
                        first_token_time_ms=ft_ms,
                        user_visible_time_ms=uv_ms,
                        completion_time=datetime.utcnow(),
                        status='error',
                        error_message='消息发送失败或网络错误',
                    )
                except Exception:
                    pass
                self._msg_svc.mark_failed(user_message_id)
            yield f"data: {json.dumps({'type': 'error', 'message': '消息发送失败，请检查网络设置'})}\n\n"

    def _safe_read_image(self, image_path: str) -> Optional[bytes]:
        try:
            from infrastructure.storage_manager import get_storage_manager
            storage = get_storage_manager()
            return storage.get_image_data(image_path)
        except Exception:
            return None

    def _prebuild_request_payload(
        self,
        *,
        user_text: str,
    user_refer_text: Optional[str],
        history: list[dict],
        image_bytes: Optional[bytes],
        client_datetime: Optional[str],
        client_language: Optional[str],
    client_timezone_offset: Optional[int],
        user_profile: Optional[str],
        is_new_conversation: bool,
    ) -> Dict[str, Any]:
        """构造与发送一致的结构化请求payload（contents 视图），便于异常时也能完整落库。"""
        model_name = getattr(self._gemini, "_model_name", "gemini-2.0-flash-exp")
        # 默认模型配置（与阶段2一致）
        cfg = {
            'max_output_tokens': 2048,
            'temperature': 0.2,
            'thinking_config': {
                'thinking_budget': 0,
                'include_thoughts': False,
            }
        }

        # 构造消息（与客户端 MessageBuilder 一致）
        builder = MessageBuilder()
        sys_prompt = SystemPrompts.get_main_prompt()
        messages = builder.build_conversation_messages(
            user_input=user_text,
            history=history,
            system_prompt=sys_prompt,
            image_data=image_bytes,
            client_datetime=client_datetime,
            client_language=client_language,
            client_timezone_offset=client_timezone_offset,
            user_profile=user_profile,
            is_new_conversation=is_new_conversation,
            user_refer_text=user_refer_text,
        )
        # 使用传输层转换为 contents，以严格对齐实际发送
        try:
            transport = getattr(self._gemini, "_transport", None)
            if transport and hasattr(transport, '_convert_messages_to_contents'):
                contents = transport._convert_messages_to_contents(messages)  # noqa: SLF001
            else:
                contents = []
        except Exception:
            contents = []

        payload_full = {
            'model': model_name,
            'config': cfg,
            'system_instruction': sys_prompt,
            'contents': contents,
            'request_id': None,
        }
        return payload_full

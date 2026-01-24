from __future__ import annotations
from typing import Generator, Iterable, Dict, Any, Optional
from copy import deepcopy
from dataclasses import dataclass
import time

from prompts.system_prompts import SystemPrompts
from api_clients.message_builder import MessageBuilder
from api_clients.response_types import StreamChunk, CompletionResponse
from api_clients.exceptions import ApiClientError, ApiTimeoutError, ApiConfigError


@dataclass
class ModelConfig:
    max_output_tokens: int = 2048
    temperature: float = 0.2
    thinking_enabled: bool = False
    stream_trigger: str = "<Sovi_Response_Msg>"
    # 可选：细化思考与缓存配置（用于日志与传输层透传）
    thinking_config: Optional[dict] = None
    cached_content: Optional[str] = None


class GeminiClient:
    """纯API客户端（阶段2框架）。
    - 不做DB操作
    - 不做XML解析
    - 仅负责：根据消息与配置构造请求、发起流式调用、返回统一的流数据
    """

    def __init__(
        self,
        transport: Any | None = None,
        model_name: Optional[str] = None,
    ) -> None:
        # transport: 注入的底层传输实现（便于mock测试）。生产环境可包装 google-genai client。
        self._transport = transport
        self._model_name = model_name or "gemini-2.0-flash-exp"
        self._message_builder = MessageBuilder()

    def _ensure_initialized(self) -> None:
        if self._transport is None:
            # 阶段2：先提供明确的错误，后续阶段注入真实transport
            raise ApiConfigError("Gemini transport not initialized")

    def chat_with_streaming(
        self,
        messages: Iterable[Dict[str, Any]],
        model_config: Optional[ModelConfig] = None,
        system_prompt: Optional[str] = None,
        client_request_id: Optional[str] = None,
    ) -> Generator[Dict[str, Any], None, None]:
        """发起流式对话，返回统一的事件流：
        - {'type': 'stream_chunk', 'text': str, 'index': int}
        - {'type': 'completion', 'raw_response': str, 'usage_tokens': int?, 'latency_ms': int?}
        """
        self._ensure_initialized()
        cfg = model_config or ModelConfig()

        # 构造底层请求负载（保持简单，后续阶段接入真实SDK）
        cfg_config: Dict[str, Any] = {
            'max_output_tokens': cfg.max_output_tokens,
            'temperature': cfg.temperature,
        }
        # 透传更细的 thinking 配置与缓存 id（如有）
        if cfg.thinking_config is not None:
            cfg_config['thinking_config'] = cfg.thinking_config
        elif cfg.thinking_enabled:
            # 与旧版保持一致的默认思考配置（开启）
            cfg_config['thinking_config'] = {
                'thinking_budget': -1,
                'include_thoughts': True,
            }
        else:
            # 默认显式关闭，便于日志对齐
            cfg_config['thinking_config'] = {
                'thinking_budget': 0,
                'include_thoughts': False,
            }
        if cfg.cached_content:
            cfg_config['cached_content'] = cfg.cached_content

        payload = {
            'model': self._model_name,
            'config': cfg_config,
            # system_instruction 在 transport 中按是否使用缓存决定是否放入 generation_config
            'system_instruction': system_prompt or SystemPrompts.get_main_prompt(),
            'messages': list(messages),
            'request_id': client_request_id,
        }

        # 预构造将要发送给SDK的 contents（使用与传输层一致的转换逻辑），以确保日志与实际请求完全一致
        try:
            if hasattr(self._transport, '_convert_messages_to_contents'):
                contents_for_sdk = self._transport._convert_messages_to_contents(payload['messages'])  # noqa: SLF001
            else:
                contents_for_sdk = []
        except Exception:
            contents_for_sdk = []
        payload['contents'] = contents_for_sdk

        start = time.time()
        raw_parts: list[str] = []
        idx = 0

        try:
            # 将底层传输返回的片段包装为统一事件
            last_raw_obj = None
            
            # 时间戳: Transport层调用开始
            from datetime import datetime
            transport_start = datetime.now()
            print(f"[PERF][transport] Transport call started: {transport_start.isoformat()}")
            
            first_chunk_logged = False
            for item in self._transport.stream_generate(payload):
                # 时间戳: Transport首次返回
                if not first_chunk_logged:
                    transport_first_chunk = datetime.now()
                    print(f"[PERF][transport] First chunk received: {transport_first_chunk.isoformat()}")
                    first_chunk_logged = True
                    
                # 文本片段
                if isinstance(item, str):
                    raw_parts.append(item)
                    yield {"type": "stream_chunk", "text": item, "index": idx}
                    idx += 1
                # 一些SDK可能返回对象，尝试提取text属性
                elif hasattr(item, 'text') and isinstance(getattr(item, 'text'), str):
                    text = getattr(item, 'text') or ""
                    raw_parts.append(text)
                    last_raw_obj = item
                    yield {"type": "stream_chunk", "text": text, "index": idx, "_raw": item}
                    idx += 1
                else:
                    # 未知类型，安全地转字符串
                    s = str(item)
                    raw_parts.append(s)
                    last_raw_obj = item
                    yield {"type": "stream_chunk", "text": s, "index": idx, "_raw": item}
                    idx += 1

            # 构造“完整原始请求”的可落库副本（以 contents 为准，严格与实际发送一致；仅去除二进制图片）
            def _serialize_contents_for_logging(contents_obj) -> list[dict]:
                serial: list[dict] = []
                try:
                    for c in contents_obj or []:
                        role = getattr(c, 'role', None) or (c.get('role') if isinstance(c, dict) else 'user')
                        parts_serial: list[dict] = []
                        parts = getattr(c, 'parts', None) or (c.get('parts') if isinstance(c, dict) else [])
                        for p in parts or []:
                            if hasattr(p, 'text') and isinstance(getattr(p, 'text'), str):
                                parts_serial.append({'text': getattr(p, 'text')})
                            elif hasattr(p, 'inline_data') and getattr(p.inline_data, 'mime_type', None):
                                # 仅记录存在图片与其mime类型，不落二进制
                                parts_serial.append({'inline_data': {'mime_type': getattr(p.inline_data, 'mime_type'), 'data': True}})
                            else:
                                # 兜底：字符串化
                                parts_serial.append({'text': str(p)})
                        serial.append({'role': role, 'parts': parts_serial})
                except Exception:
                    pass
                return serial

            # 当启用缓存（cached_content）时，系统提示通过缓存下发，落库的完整请求应不包含 system_instruction
            request_payload_full = {
                'model': payload['model'],
                'config': payload['config'],
                'contents': _serialize_contents_for_logging(contents_for_sdk),
                'request_id': payload.get('request_id'),
            }
            if not payload['config'].get('cached_content'):
                request_payload_full['system_instruction'] = payload.get('system_instruction')

            # 结束时发出completion事件
            latency_ms = int((time.time() - start) * 1000)
            yield {
                "type": "completion",
                "raw_response": "".join(raw_parts),
                "usage_tokens": None,
                "latency_ms": latency_ms,
                "_final_raw": last_raw_obj,
                # 完整原始请求（仅去除图片二进制），用于API请求表落库
                "request_payload_full": request_payload_full,
            }
        except TimeoutError as e:
            raise ApiTimeoutError(str(e))
        except ApiClientError:
            raise
        except Exception as e:
            raise ApiClientError(str(e))

    # 便捷方法：从原始输入构造消息并流式提交（兼容旧调用风格）
    def chat_with_streaming_from_raw(
        self,
        user_input: str,
        history: Optional[list[dict]] = None,
        system_prompt: Optional[str] = None,
        image_data: Optional[bytes] = None,
        client_datetime: Optional[str] = None,
        client_language: Optional[str] = None,
    client_timezone_offset: Optional[int] = None,
        user_profile: Optional[str] = None,
        is_new_conversation: bool = False,
        model_config: Optional[ModelConfig] = None,
        client_request_id: Optional[str] = None,
    user_refer_text: Optional[str] = None,
    ) -> Generator[Dict[str, Any], None, None]:
        effective_system_prompt = system_prompt or SystemPrompts.get_main_prompt()
        messages = self._message_builder.build_conversation_messages(
            user_input=user_input,
            history=history,
            system_prompt=effective_system_prompt,
            image_data=image_data,
            client_datetime=client_datetime,
            client_language=client_language,
            client_timezone_offset=client_timezone_offset,
            user_profile=user_profile,
            is_new_conversation=is_new_conversation,
            user_refer_text=user_refer_text,
        )
        yield from self.chat_with_streaming(
            messages=messages,
            model_config=model_config,
            system_prompt=effective_system_prompt,
            client_request_id=client_request_id,
        )

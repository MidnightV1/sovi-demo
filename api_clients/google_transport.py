from __future__ import annotations
from typing import Generator, Dict, Any, Optional
import os
import time
import logging
from google import genai
from google.genai import types

from api_clients.exceptions import ApiClientError, ApiTimeoutError, ApiConfigError

logger = logging.getLogger(__name__)


class GoogleTransport:
    """Google Gemini API 传输层实现
    
    封装与Google Gemini SDK的底层通信，包括：
    - 客户端初始化和API密钥管理
    - 流式请求发送和超时控制
    - 响应数据提取和错误处理
    """
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or self._get_api_key()
        self.client = None
        self._init_client()
    
    def _get_api_key(self) -> str:
        """获取API密钥，参考旧代码的逻辑"""
        # 直接使用环境变量
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            raise ApiConfigError("环境变量GEMINI_API_KEY未设置")
        return api_key
    
    def _init_client(self):
        """初始化Gemini客户端"""
        try:
            self.client = genai.Client(api_key=self.api_key)
            logger.info("Google Gemini传输层初始化成功")
        except Exception as e:
            logger.error(f"Google Gemini传输层初始化失败: {str(e)}")
            self.client = None
            raise ApiConfigError(f"Gemini客户端初始化失败: {str(e)}")
    
    def stream_generate(self, payload: Dict[str, Any]) -> Generator[str, None, None]:
        """发起流式生成请求
        
        Args:
            payload: 请求负载，包含model、config、system_instruction、messages等
            
        Yields:
            str: 流式文本片段
            
        Raises:
            ApiConfigError: 客户端未初始化
            ApiTimeoutError: 请求超时
            ApiClientError: 其他API错误
        """
        if not self.client:
            raise ApiConfigError("Gemini客户端未初始化")
        
        try:
            # 构建generation_config，参考旧代码结构
            config_data = payload.get('config', {})
            generation_config = types.GenerateContentConfig(
                max_output_tokens=config_data.get('max_output_tokens', 2048),
                temperature=config_data.get('temperature', 0.2),
            )
            
            # 处理thinking配置
            thinking_config = config_data.get('thinking_config', None)
            if thinking_config is not None:
                generation_config.thinking_config = types.ThinkingConfig(
                    thinking_budget=thinking_config.get('thinking_budget', 0),
                    include_thoughts=thinking_config.get('include_thoughts', False)
                )
            else:
                # 与旧版一致：未显式设置时也传递关闭思考的配置
                generation_config.thinking_config = types.ThinkingConfig(
                    thinking_budget=0,
                    include_thoughts=False,
                )
            
            # 处理缓存或系统指令
            if 'cached_content' in config_data:
                generation_config.cached_content = config_data['cached_content']
            elif 'system_instruction' in payload:
                generation_config.system_instruction = payload['system_instruction']
            
            # 转换messages为contents格式（若已由上层预构建则直接使用）
            if 'contents' in payload and payload['contents'] is not None:
                contents = payload['contents']
            else:
                contents = self._convert_messages_to_contents(payload.get('messages', []))
            
            # 发送流式请求
            # 时间戳: HTTP请求发起
            from datetime import datetime
            http_start = datetime.now()
            print(f"[PERF][HTTP] Request sent: {http_start.isoformat()}")
            
            response = self.client.models.generate_content_stream(
                model=payload['model'],
                config=generation_config,
                contents=contents
            )
            
            # 流式超时检测，参考旧代码
            start_time = time.time()
            last_chunk_time = time.time()
            STREAM_TIMEOUT = 60  # 60秒总超时
            CHUNK_TIMEOUT = 30   # 30秒无数据超时
            
            # 处理流式输出 - 直接返回原始Google API chunk对象
            first_http_chunk = True
            for chunk in response:
                current_time = time.time()
                
                # 时间戳: HTTP首次响应
                if first_http_chunk:
                    http_first_response = datetime.now()
                    print(f"[PERF][HTTP] First response: {http_first_response.isoformat()}")
                    first_http_chunk = False
                
                # 检查总超时
                if current_time - start_time > STREAM_TIMEOUT:
                    raise ApiTimeoutError("流式响应总时间超时")
                
                # 检查数据间隔超时  
                if current_time - last_chunk_time > CHUNK_TIMEOUT:
                    raise ApiTimeoutError("流式响应数据间隔超时")
                
                last_chunk_time = current_time
                
                # 直接返回原始chunk对象，与旧架构保持一致
                yield chunk
                    
        except ApiTimeoutError:
            raise
        except ApiClientError:
            raise
        except Exception as e:
            logger.error(f"Google API调用失败: {str(e)}")
            raise ApiClientError(f"Google API调用失败: {str(e)}")
    
    def _convert_messages_to_contents(self, messages: list) -> list:
        """将标准消息格式转换为Google API的contents格式
        
        MessageBuilder返回的格式：
        [
            {"role": "system", "content": "..."},
            {"role": "user", "content": "...", "image_data": bytes},
            ...
        ]
        
        需要转换为Google API的types.Content格式
        """
        contents = []
        
        for msg in messages:
            role = msg.get('role', 'user')
            # 映射角色：system不直接转换，user保持user，其他映射为model
            if role == 'system':
                continue  # system prompt通过generation_config处理
            elif role in ['server', 'assistant']:
                role = 'model'
            # else: role = 'user'
            
            content_text = msg.get('content', '')
            # 仅对“当前这一轮用户消息”做包装：用 meta.blocks 的存在作为判定
            meta = msg.get('meta') or {}
            blocks = (meta.get('blocks') or {}) if isinstance(meta, dict) else {}
            has_current_blocks = bool(blocks.get('datetime') or blocks.get('profile') or blocks.get('user_refer'))
            if role == 'user' and has_current_blocks:
                # 先拼接时间/画像块（位于标签外部）
                prefix_blocks = f"{blocks.get('datetime','')}{blocks.get('profile','')}{blocks.get('user_refer','')}"
                is_new_conv = bool(meta.get('is_new_conversation'))
                if is_new_conv:
                    content_text = f"{prefix_blocks}<|server_command_begin|>\n{content_text}\n<|server_command_end|>"
                else:
                    if content_text.strip():
                        content_text = f"{prefix_blocks}<|user_text_begin|>\n{content_text}\n<|user_text_end|>"
                    else:
                        content_text = f"{prefix_blocks}<|user_text_begin|>\n\n<|user_text_end|>"
            parts = []
            
            # 处理图片（如果有）
            image_data = msg.get('image_data')
            image_url = msg.get('image_url')
            loaded_bytes = None
            if image_data:
                loaded_bytes = image_data
            elif image_url:
                # 历史图片：优先存储读取，失败再尝试 http(s) 下载
                try:
                    try:
                        from infrastructure.storage_manager import get_storage_manager
                        storage = get_storage_manager()
                        loaded_bytes = storage.get_image_data(image_url)
                    except Exception:
                        loaded_bytes = None
                    if (not loaded_bytes) and str(image_url).startswith(("http://", "https://")):
                        loaded_bytes = self._download_image_with_retry(image_url)
                except Exception as e:
                    logger.warning(f"获取历史图片失败，跳过图片: {str(e)}")
            if loaded_bytes:
                try:
                    mime_type = self._infer_image_mime(loaded_bytes)
                    parts.append(types.Part.from_bytes(
                        data=loaded_bytes,
                        mime_type=mime_type
                    ))
                except Exception as e:
                    logger.warning(f"生成图片Part失败，跳过图片: {str(e)}")
            
            # 处理文本部分（根据Gemini API要求，即使是纯图片消息也需要包含文本部分）
            parts.append(types.Part.from_text(text=content_text))
            
            if parts:
                contents.append(types.Content(role=role, parts=parts))
        
        return contents

    def _download_image_with_retry(self, image_url: str, max_retries: int = 5) -> Optional[bytes]:
        """下载图片，支持重试机制（用于历史消息 http(s) 图片）。"""
        import time as _time
        import requests
        for attempt in range(max_retries):
            try:
                resp = requests.get(image_url, timeout=10)
                resp.raise_for_status()
                return resp.content
            except Exception as e:
                if attempt == max_retries - 1:
                    logger.warning(f"图片下载彻底失败: {image_url}; err={e}")
                    return None
                _time.sleep(1)
    
    def _infer_image_mime(self, image_bytes: bytes) -> str:
        """根据图片二进制内容推断 MIME 类型，参考旧代码逻辑"""
        try:
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(image_bytes))
            fmt = (img.format or '').upper()
            mapping = {
                'JPEG': 'image/jpeg',
                'JPG': 'image/jpeg',
                'PNG': 'image/png',
                'WEBP': 'image/webp',
                'GIF': 'image/gif',
                'BMP': 'image/bmp',
                'TIFF': 'image/tiff'
            }
            return mapping.get(fmt, 'image/jpeg')
        except Exception:
            return 'image/jpeg'

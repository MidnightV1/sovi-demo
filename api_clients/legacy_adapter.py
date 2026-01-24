from __future__ import annotations
from typing import Generator, Optional, Dict, Any
import logging

from api_clients.gemini_client import GeminiClient, ModelConfig
from api_clients.exceptions import ApiClientError

logger = logging.getLogger(__name__)


class LegacyGeminiAdapter:
    """旧接口适配器
    
    将新的GeminiClient适配为旧的chat_with_streaming接口，
    确保现有代码无需修改即可使用新架构。
    
    主要职责：
    - 参数格式转换
    - 响应格式兼容
    - 错误处理适配
    """
    
    def __init__(self, new_client: GeminiClient):
        self._client = new_client
    
    def chat_with_streaming(self, 
                            user_input: str, 
                            user_id: int,
                            image_data: Optional[bytes] = None,
                            user_profile: Optional[str] = None,
                            conversation_id: int = None,
                            message_id: int = None,
                            thinking: bool = False,
                            model_name: str = None,
                            stream_trigger: str = "<Sovi_Response_Msg>",
                            client_datetime: str = None,
                            client_language: str = None,
                            client_timezone_offset: Optional[int] = None,
                            is_new_conversation: bool = False,
                            session_context: str = None) -> Generator[str, None, None]:
        """适配旧接口到新客户端
        
        完全兼容旧的chat_with_streaming接口，参数和返回值保持一致
        """
        try:
            # 构建ModelConfig
            model_config = ModelConfig(
                thinking_enabled=thinking,
                stream_trigger=stream_trigger
            )
            
            # 这里需要获取历史对话，但新架构不应该直接访问数据库
            # 需要确认：历史对话应该由上层传入还是在这里获取？
            history = self._get_conversation_history(conversation_id, message_id) if conversation_id else None
            
            # 调用新客户端的便捷方法，直接转发原始流
            for chunk in self._client.chat_with_streaming_from_raw(
                user_input=user_input,
                history=history,
                image_data=image_data,
                client_datetime=client_datetime,
                client_language=client_language,
                client_timezone_offset=client_timezone_offset,
                user_profile=user_profile,
                is_new_conversation=is_new_conversation,
                model_config=model_config,
                client_request_id=f"{user_id}_{message_id}" if message_id else None
            ):
                # 直接转发原始Google API chunk对象，保持与旧架构完全兼容
                yield chunk
                    
        except Exception as e:
            logger.error(f"LegacyAdapter调用失败: {str(e)}")
            # 兼容旧的错误处理方式
            raise Exception(f"服务暂时不可用，请稍后重试: {str(e)}")
    
    def _get_conversation_history(self, conversation_id: int, exclude_message_id: int = None) -> list:
        """获取对话历史
        
        这里有个设计问题：新架构应该避免直接访问数据库，
        但为了兼容性，可能需要在适配器中临时保留这个功能。
        
        需要确认：
        1. 是否在适配器中直接访问数据库？
        2. 还是修改上层调用方式，预先传入历史？
        """
        try:
            # 临时方案：直接使用旧代码的数据库访问逻辑
            from config import Config
            if not conversation_id:
                return []
                
            db_manager = Config.get_database_manager()
            history = db_manager.get_conversation_history(conversation_id, limit=20)
            
            # 如果指定了要排除的消息ID，则过滤掉该消息
            if exclude_message_id:
                history = [msg for msg in history if msg.get('message_id') != exclude_message_id]
                
            logger.info(f"适配器获取到 {len(history)} 条历史对话记录")
            return history
        except Exception as e:
            logger.warning(f"适配器获取历史对话失败: {str(e)}")
            return []

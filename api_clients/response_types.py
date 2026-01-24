from __future__ import annotations
from dataclasses import dataclass
from typing import TypedDict, Optional, Literal, Dict, Any
from enum import Enum
from datetime import datetime


# 默认欢迎消息列表（API调用失败时的备用选项）
DEFAULT_WELCOME_MESSAGES = [
    "你好！我是Sovi，你的AI学习伙伴！有什么可以帮助你的吗？",
    "欢迎使用Sovi！我在这里为你提供学习支持和问题解答。",
    "你好！很高兴与你交流，我是你的AI助手Sovi，随时为你服务！",
    "欢迎来到Sovi！我是你的学习伙伴，让我们开始一段有意义的对话吧！",
    "嗨！我是Sovi，你的智能学习助手。今天想学习什么呢？"
]


class ChunkType(str, Enum):
    STREAM_CHUNK = 'stream_chunk'
    COMPLETION = 'completion'
    ERROR = 'error'


class StreamChunk(TypedDict, total=False):
    # 新契约字段
    type: Literal['stream_chunk']
    content: str
    timestamp: float
    chunk_number: int
    # 兼容旧字段
    text: str
    index: int


class CompletionResponse(TypedDict, total=False):
    type: Literal['completion']
    raw_response: str
    usage_tokens: Optional[int]
    latency_ms: Optional[int]


@dataclass
class ParsedXmlData:
    """解析后的XML数据（等价字段以兼容旧逻辑）。"""
    # 基础
    raw_response: Optional[str] = None
    display_content: Optional[str] = None
    working_content: Optional[str] = None
    error: Optional[str] = None
    raw_text: Optional[str] = None

    # 行为/模式
    action_mode: Optional[str] = None
    is_valid_question: Optional[bool] = None

    # 内容
    explanation: Optional[str] = None
    response_msg: Optional[str] = None

    # 元数据
    session_meta: Optional[Dict[str, Any]] = None
    question_meta: Optional[Dict[str, Any]] = None
    profile_update: Optional[Dict[str, Any]] = None
    
    def get(self, key: str, default=None):
        """提供字典式的 .get() 方法，保持与旧代码的兼容性"""
        return getattr(self, key, default)
    
    def to_dict(self):
        """转换为字典，用于JSON序列化"""
        from dataclasses import asdict
        return asdict(self)

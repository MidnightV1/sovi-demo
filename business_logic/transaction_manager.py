from __future__ import annotations
from typing import ContextManager, Dict, Any, Optional
import json
import uuid
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


def _safe_json_serialize(obj: Any) -> Any:
    """Recursively convert non-JSON-serializable objects to serializable format."""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [_safe_json_serialize(item) for item in obj]
    if isinstance(obj, dict):
        return {str(k): _safe_json_serialize(v) for k, v in obj.items()}
    # Handle datetime
    if isinstance(obj, datetime):
        return obj.isoformat()
    # Handle bytes
    if isinstance(obj, bytes):
        return "<binary data>"
    # Handle objects with __dict__
    if hasattr(obj, '__dict__'):
        try:
            return {str(k): _safe_json_serialize(v) for k, v in obj.__dict__.items() if not k.startswith('_')}
        except Exception:
            return str(obj)
    # Fallback to string representation
    try:
        return str(obj)
    except Exception:
        return "<unserializable>"


class TransactionManager:
    """
    简单的事务管理器：基于 DatabaseManager.engine 提供的连接与 begin() 封装。
    - 仅在需要“短事务”时使用（例如流结束后一次性提交AI消息及相关元数据）。
    - 流期间不持有事务，避免长事务锁。
    """

    def __init__(self, db) -> None:
        self._db = db

    def begin(self) -> ContextManager:
        """返回一个上下文管理器，用于 with 语法开启/提交事务。"""
        engine = getattr(self._db, 'engine', None)
        if engine is None:
            raise RuntimeError('TransactionManager requires a db with an SQLAlchemy engine')
        conn = engine.connect()
        tx = conn.begin()

        class _Tx(ContextManager):
            def __enter__(self_inner):
                self_inner.conn = conn
                self_inner.tx = tx
                return self_inner

            def __exit__(self_inner, exc_type, exc, tb):
                if exc_type is None:
                    try:
                        self_inner.tx.commit()
                    finally:
                        self_inner.conn.close()
                else:
                    try:
                        self_inner.tx.rollback()
                    finally:
                        self_inner.conn.close()
                # 让异常按默认传播（False）
                return False

            # 便捷：提供执行SQL的方法以适配 db 层调用风格（可选）
            def execute(self_inner, *args, **kwargs):
                return self_inner.conn.execute(*args, **kwargs)

        return _Tx()

    def save_api_request_log(
        self,
        user_id: int,
        conversation_id: Optional[int],
        message_id: Optional[int],
        model_name: str,
        request_data: Dict[str, Any],
        raw_response: str,
        full_response: str,
    final_chunk: Any = None,
    *,
    request_start_time: Optional[datetime] = None,
    first_token_time_ms: Optional[int] = None,
    user_visible_time_ms: Optional[int] = None,
    completion_time: Optional[datetime] = None,
    status: str = 'success',
    error_message: Optional[str] = None,
    session_context: Optional[str] = None,
    request_type: str = 'gemini_text',
    has_current_image: Optional[bool] = None,
    image_data_info: Optional[str] = None,
    used_cache: Optional[bool] = None,
    cache_name: Optional[str] = None,
    cached_tokens: Optional[int] = None,
    cache_cost_usd: Optional[str] = None,
    cache_cost_cny: Optional[str] = None,
    retry_count: int = 0
    ) -> str:
        """
        保存API请求日志
        从旧gemini_client._log_api_request迁移而来的逻辑
        """
        try:
            # 生成请求ID
            request_id = str(uuid.uuid4())
            
            # 提取token使用信息
            input_tokens = 0
            output_tokens = 0
            usage_metadata = None
            
            if final_chunk and hasattr(final_chunk, 'usage_metadata'):
                usage_metadata = final_chunk.usage_metadata
                if usage_metadata:
                    input_tokens = getattr(usage_metadata, 'prompt_token_count', 0) or 0
                    output_tokens = getattr(usage_metadata, 'candidates_token_count', 0) or 0
                    # 包含思考token
                    if hasattr(usage_metadata, 'thoughts_token_count') and usage_metadata.thoughts_token_count:
                        output_tokens += usage_metadata.thoughts_token_count
            
            # 若未显式传入缓存成本，则根据 cached_tokens 计算（集中处理，避免各调用点重复）
            cache_cost_usd_out = cache_cost_usd
            cache_cost_cny_out = cache_cost_cny
            try:
                if (cache_cost_usd_out is None or cache_cost_cny_out is None):
                    ct = cached_tokens or 0
                    if ct > 0:
                        # 以最终统计到的 input_tokens 作为总输入tokens（其中已包含缓存tokens）
                        from tools.cost_calculator import CostCalculator
                        calc = CostCalculator.calculate_cost(model_name, input_tokens or 0, output_tokens or 0, cached_tokens=ct)
                        cache_cost_usd_out = calc.get('cache_cost_usd') or "0.000000"
                        try:
                            rate = getattr(CostCalculator, 'USD_TO_CNY_RATE', 7.3)
                            cache_cost_cny_out = f"{float(cache_cost_usd_out) * rate:.4f}"
                        except Exception:
                            cache_cost_cny_out = "0.0000"
                # 兜底：无缓存或仍未赋值时写入0，避免空值
                if cache_cost_usd_out is None:
                    cache_cost_usd_out = "0.000000"
                if cache_cost_cny_out is None:
                    cache_cost_cny_out = "0.0000"
            except Exception:
                # 计算失败时亦兜底为0
                cache_cost_usd_out = "0.000000"
                cache_cost_cny_out = "0.0000"

            # 补充：统一推断是否包含当前图片（优先使用传入参数；否则从请求负载推断）
            def _infer_has_image_from_request(req: Any) -> Optional[bool]:
                try:
                    if not isinstance(req, dict):
                        return None
                    # 优先看 contents（来自 SDK 视图或我们序列化的视图）
                    contents = req.get('contents')
                    if isinstance(contents, list):
                        for c in contents:
                            parts = None
                            if hasattr(c, 'parts'):
                                parts = getattr(c, 'parts')
                            elif isinstance(c, dict):
                                parts = c.get('parts')
                            if not parts:
                                continue
                            for p in parts:
                                # 我们的序列化视图中，图片为 {'inline_data': {'mime_type': ..., 'data': True}}
                                if isinstance(p, dict) and p.get('inline_data'):
                                    return True
                                # SDK 对象（尽量避免，但做兜底判断）
                                if hasattr(p, 'inline_data'):
                                    return True
                    # 其次看 messages（原始消息视图）
                    messages = req.get('messages')
                    if isinstance(messages, list):
                        for m in messages:
                            if isinstance(m, dict) and (m.get('image_data') or m.get('image_url')):
                                return True
                    # 兼容旧字段
                    if 'has_image' in req:
                        return bool(req.get('has_image'))
                except Exception:
                    return None
                return None

            inferred_has_image = has_current_image
            if inferred_has_image is None:
                inferred_has_image = _infer_has_image_from_request(request_data)
            # 若仍无法判定，默认为 False，避免DB出现 NULL（业务上更符合语义：当前未包含图片）
            if inferred_has_image is None:
                inferred_has_image = False

            # 根据图片存在性自动设定请求类型（仅在未显式指定或默认文本类型时切换）
            request_type_out = request_type
            try:
                if (request_type_out is None or request_type_out == 'gemini_text') and bool(inferred_has_image):
                    request_type_out = 'gemini_vision'
            except Exception:
                request_type_out = request_type

            # 构建请求数据
            api_log_data = {
                'request_id': request_id,
                'user_id': user_id,
                'conversation_id': conversation_id,
                'message_id': message_id,
                'session_context': session_context,
                'request_type': request_type_out,
                'model_name': model_name,
                'request_data': json.dumps(_safe_json_serialize(request_data), ensure_ascii=False),
                'raw_response': raw_response,
                'response_meta': json.dumps(_safe_json_serialize(self._extract_response_metadata(final_chunk)), ensure_ascii=False),
                'input_tokens': input_tokens,
                'output_tokens': output_tokens,
                'total_tokens': input_tokens + output_tokens,
                'request_start_time': request_start_time or datetime.utcnow(),
                'first_token_time_ms': first_token_time_ms,
                'user_visible_time_ms': user_visible_time_ms,
                'completion_time': completion_time or datetime.utcnow(),
                'status': status,
                'error_message': error_message,
                # 与表结构对齐的可选字段
                'has_current_image': inferred_has_image,
                'image_data_info': image_data_info,
                'used_cache': used_cache,
                'cache_name': cache_name,
                'cached_tokens': cached_tokens,
                'cache_cost_usd': cache_cost_usd_out,
                'cache_cost_cny': cache_cost_cny_out,
                'retry_count': retry_count,
            }
            
            # 保存到数据库
            saved_request_id = self._db.save_api_request_log(api_log_data)
            if not saved_request_id:
                logger.error("保存API请求日志失败：数据库未返回请求ID")
            else:
                logger.info(f"API请求日志已保存: {saved_request_id}")
            return saved_request_id
            
        except Exception as e:
            logger.error(f"保存API请求日志失败: {str(e)}")
            return request_id  # 返回生成的ID，即使保存失败
    
    def _extract_response_metadata(self, final_chunk: Any) -> Dict[str, Any]:
        """提取响应元数据，参考旧代码逻辑"""
        if not final_chunk:
            return {}
        
        metadata = {}
        
        # 模型版本信息
        if hasattr(final_chunk, 'model_version'):
            metadata['model_version'] = final_chunk.model_version
        
        # 响应ID
        if hasattr(final_chunk, 'response_id'):
            metadata['response_id'] = final_chunk.response_id
        
        # Token使用统计
        if hasattr(final_chunk, 'usage_metadata') and final_chunk.usage_metadata:
            usage = final_chunk.usage_metadata
            metadata['usage_metadata'] = {
                'prompt_token_count': getattr(usage, 'prompt_token_count', None),
                'candidates_token_count': getattr(usage, 'candidates_token_count', None),
                'total_token_count': getattr(usage, 'total_token_count', None),
                'cached_content_token_count': getattr(usage, 'cached_content_token_count', None),
                'thoughts_token_count': getattr(usage, 'thoughts_token_count', None),
            }
        
        return metadata


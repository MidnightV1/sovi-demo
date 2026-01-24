"""
系统缓存管理模块
负责 Gemini API 的 system prompt 缓存管理
按照 Gemini API 原生逻辑设计：一个模型一个系统缓存
"""

import logging
import json
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from sqlalchemy import text
from google import genai
from google.genai import types
from config import Config

logger = logging.getLogger(__name__)

class SystemCacheManager:
    """
    系统缓存管理器 - 简化设计，按照Gemini API原生逻辑
    """
    
    def __init__(self, gemini_client):
        self.client = gemini_client.client  # Gemini client 实例
        self.db = Config.get_database_manager()
        self.cache_ttl_hours = 2  # 缓存有效期2小时
        
    def get_or_create_system_cache(self, model_name: str, system_instruction: str) -> Optional[str]:
        """
        获取或创建系统缓存（按照Gemini API原生逻辑）
        一个模型只维护一个系统指令缓存
        
        Args:
            model_name: 模型名称
            system_instruction: 系统指令内容
            
        Returns:
            str: API缓存名称（如cachedContents/xxxxx），如果失败返回None
        """
        try:
            # 1. 检查是否已有该模型的缓存
            existing_cache = self._get_existing_cache_for_model(model_name)
            
            if existing_cache:
                # 2. 验证系统指令是否匹配
                if self._is_instruction_matching(existing_cache, system_instruction):
                    # 3. 验证缓存是否仍然有效
                    if self._is_cache_still_valid(existing_cache['api_cache_name']):
                        # 4. 更新使用统计
                        self._update_cache_usage(existing_cache['id'])
                        logger.info(f"重用现有缓存: {existing_cache['api_cache_name']}")
                        return existing_cache['api_cache_name']
                    else:
                        # 5. 缓存过期，清理记录
                        self._cleanup_expired_cache(existing_cache['id'])
                        logger.info(f"缓存过期，已清理: {existing_cache['api_cache_name']}")
                else:
                    # 6. 系统指令不匹配，删除旧缓存
                    self._cleanup_expired_cache(existing_cache['id'])
                    logger.info(f"系统指令变更，已清理旧缓存: {existing_cache['api_cache_name']}")
            
            # 7. 创建新缓存
            api_cache_name = self._create_new_system_cache(model_name, system_instruction)
            return api_cache_name
            
        except Exception as e:
            logger.error(f"获取或创建系统缓存失败: {e}")
            return None
    
    def _get_existing_cache_for_model(self, model_name: str) -> Optional[Dict]:
        """获取指定模型的现有缓存记录"""
        try:
            with self.db.engine.connect() as conn:
                result = conn.execute(
                    text("SELECT * FROM system_cache_status WHERE model_name = :model_name"),
                    {"model_name": model_name}
                )
                row = result.fetchone()
                if row:
                    return {
                        'id': row[0],
                        'model_name': row[1],
                        'api_cache_name': row[2],
                        'system_instruction_hash': row[3],
                        'token_count': row[4],
                        'expire_time': row[5],
                        'last_used': row[6],
                        'usage_count': row[7]
                    }
        except Exception as e:
            logger.error(f"获取模型缓存记录失败: {e}")
        return None
    
    def _is_instruction_matching(self, cache_record: Dict, system_instruction: str) -> bool:
        """检查系统指令是否匹配"""
        instruction_hash = hashlib.md5(system_instruction.encode('utf-8')).hexdigest()
        return cache_record['system_instruction_hash'] == instruction_hash
    
    def _is_cache_still_valid(self, api_cache_name: str) -> bool:
        """通过API检查缓存是否仍然有效"""
        try:
            cache = self.client.caches.get(name=api_cache_name)
            if cache:
                # 检查过期时间
                if hasattr(cache, 'expire_time'):
                    if isinstance(cache.expire_time, str):
                        expire_time = datetime.fromisoformat(cache.expire_time.replace('Z', '+00:00'))
                    else:
                        expire_time = cache.expire_time
                    return expire_time > datetime.now(expire_time.tzinfo)
                return True
        except Exception as e:
            logger.warning(f"检查缓存有效性失败: {e}")
        return False
    
    def _update_cache_usage(self, cache_id: int):
        """更新缓存使用统计"""
        try:
            with self.db.engine.connect() as conn:
                conn.execute(
                    text("""
                        UPDATE system_cache_status 
                        SET usage_count = usage_count + 1, 
                            last_used = :last_used,
                            updated_at = :updated_at
                        WHERE id = :cache_id
                    """),
                    {
                        "last_used": datetime.utcnow(),
                        "updated_at": datetime.utcnow(),
                        "cache_id": cache_id
                    }
                )
                conn.commit()
        except Exception as e:
            logger.error(f"更新缓存使用统计失败: {e}")
    
    def _cleanup_expired_cache(self, cache_id: int):
        """清理过期或无效的缓存记录"""
        try:
            with self.db.engine.connect() as conn:
                conn.execute(
                    text("DELETE FROM system_cache_status WHERE id = :cache_id"),
                    {"cache_id": cache_id}
                )
                conn.commit()
                logger.info(f"已清理缓存记录: {cache_id}")
        except Exception as e:
            logger.error(f"清理缓存记录失败: {e}")
    
    def _create_new_system_cache(self, model_name: str, system_instruction: str) -> Optional[str]:
        """创建新的系统缓存"""
        try:
            # 估算token数量
            token_count = self._estimate_tokens(system_instruction)
            
            # 检查是否满足最少token要求
            min_tokens = 1024 if '2.5-flash' in model_name.lower() else 4096
            if token_count < min_tokens:
                logger.warning(f"系统指令token数量({token_count})不足最小要求({min_tokens})，跳过缓存创建")
                return None
            
            # 创建缓存
            ttl_seconds = int(self.cache_ttl_hours * 3600)
            logger.info(f"创建缓存，TTL: {ttl_seconds}秒")
            
            cache = self.client.caches.create(
                model=model_name,
                config=types.CreateCachedContentConfig(
                    display_name=f"system_prompt_{datetime.now().strftime('%Y%m%d_%H%M')}",
                    system_instruction=system_instruction,
                    ttl=f"{ttl_seconds}s"
                )
            )
            
            # 计算缓存成本（包含CNY）
            from tools.cost_calculator import CostCalculator
            cache_cost_info = CostCalculator.calculate_cache_cost(token_count, self.cache_ttl_hours, model_name)
            
            # 处理过期时间
            if isinstance(cache.expire_time, str):
                expire_time = datetime.fromisoformat(cache.expire_time.replace('Z', '+00:00'))
            elif hasattr(cache.expire_time, 'isoformat'):
                expire_time = cache.expire_time
            else:
                expire_time = datetime.utcnow() + timedelta(hours=self.cache_ttl_hours)
            
            # 保存到数据库
            self._save_cache_to_db(
                model_name=model_name,
                api_cache_name=cache.name,
                system_instruction=system_instruction,
                token_count=token_count,
                expire_time=expire_time,
                cache_cost_info=cache_cost_info
            )
            
            logger.info(f"新缓存创建成功: {cache.name}, tokens: {token_count}, cost: ${cache_cost_info['total_cost_usd']}")
            return cache.name
            
        except Exception as e:
            logger.error(f"创建新缓存失败: {e}")
            return None
    
    def _save_cache_to_db(self, model_name: str, api_cache_name: str, system_instruction: str,
                         token_count: int, expire_time: datetime, cache_cost_info: Dict):
        """保存缓存信息到数据库"""
        try:
            # 生成系统指令哈希
            instruction_hash = hashlib.md5(system_instruction.encode('utf-8')).hexdigest()
            
            with self.db.engine.connect() as conn:
                conn.execute(
                    text("""
                        INSERT INTO system_cache_status 
                        (model_name, api_cache_name, system_instruction_hash, token_count, 
                         expire_time, last_used, usage_count, cache_cost_usd, cache_cost_cny,
                         total_saved_usd, total_saved_cny, created_at, updated_at)
                        VALUES (:model_name, :api_cache_name, :instruction_hash, :token_count,
                                :expire_time, :last_used, 1, :cache_cost_usd, :cache_cost_cny,
                                '0.000000', '0.0000', :created_at, :updated_at)
                    """),
                    {
                        "model_name": model_name,
                        "api_cache_name": api_cache_name,
                        "instruction_hash": instruction_hash,
                        "token_count": token_count,
                        "expire_time": expire_time,
                        "last_used": datetime.utcnow(),
                        "cache_cost_usd": cache_cost_info['total_cost_usd'],
                        "cache_cost_cny": cache_cost_info['total_cost_cny'],
                        "created_at": datetime.utcnow(),
                        "updated_at": datetime.utcnow()
                    }
                )
                conn.commit()
        except Exception as e:
            logger.error(f"保存缓存信息到数据库失败: {e}")
    
    def _estimate_tokens(self, text: str) -> int:
        """估算文本的token数量（简单估算）"""
        # 简单估算：英文约4个字符/token，中文约1.5个字符/token
        char_count = len(text)
        chinese_chars = sum(1 for char in text if '\u4e00' <= char <= '\u9fff')
        english_chars = char_count - chinese_chars
        return int(english_chars / 4 + chinese_chars / 1.5)

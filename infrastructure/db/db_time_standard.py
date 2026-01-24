"""
数据库时间字段规范设计文档
统一所有表的时间字段处理逻辑
"""

from datetime import datetime, timezone
from tools.utils import TimeUtils

class DatabaseTimeStandard:
    """
    数据库时间字段标准
    """
    
    # ============ 时间字段命名规范 ============
    
    # 统一使用 created_at 和 updated_at 字段名
    # 不再使用 create_time, update_time 等变体
    
    CREATED_AT = 'created_at'  # 创建时间字段名
    UPDATED_AT = 'updated_at'  # 更新时间字段名
    
    # ============ 时间字段类型和默认值 ============
    
    @staticmethod
    def get_created_at_column():
        """获取标准的created_at字段定义"""
        from sqlalchemy import Column, DateTime
        return Column('created_at', DateTime, default=TimeUtils.utc_now, nullable=False)
    
    @staticmethod
    def get_updated_at_column():
        """获取标准的updated_at字段定义"""
        from sqlalchemy import Column, DateTime
        return Column('updated_at', DateTime, 
                     default=TimeUtils.utc_now, 
                     onupdate=TimeUtils.utc_now, 
                     nullable=False)
    
    # ============ 不同表类型的时间字段策略 ============
    
    class TableTimeStrategy:
        """
        表级别的时间字段策略
        """
        
        # 策略1: 完整时间跟踪 (both created_at and updated_at)
        FULL_TRACKING = "full_tracking"
        
        # 策略2: 仅创建时间 (only created_at)
        CREATE_ONLY = "create_only"
        
        # 策略3: 扩展时间跟踪 (包含deleted_at等特殊时间)
        EXTENDED_TRACKING = "extended_tracking"
    
    # ============ 各表的时间策略配置 ============
    
    TABLE_STRATEGIES = {
        # 用户相关表
        'users': {
            'strategy': TableTimeStrategy.FULL_TRACKING,
            'reason': '用户信息可能更新（密码、个人资料等）',
            'fields': ['created_at', 'updated_at']
        },
        
        'user_sessions': {
            'strategy': TableTimeStrategy.FULL_TRACKING,
            'reason': '会话状态可能更新（延期、状态变更等）',
            'fields': ['created_at', 'updated_at']
        },
        
        'user_profiles': {
            'strategy': TableTimeStrategy.FULL_TRACKING,
            'reason': '用户画像经常更新',
            'fields': ['created_at', 'updated_at']
        },
        
        # 对话相关表
        'conversations': {
            'strategy': TableTimeStrategy.EXTENDED_TRACKING,
            'reason': '对话有创建、更新、删除等完整生命周期',
            'fields': ['created_at', 'updated_at', 'deleted_at']
        },
        
        'messages': {
            'strategy': TableTimeStrategy.FULL_TRACKING,
            'reason': '消息虽不常更新，但可能有编辑、状态变更需求',
            'fields': ['created_at', 'updated_at']
        },
        
        # 元数据和日志表
        'question_metadata': {
            'strategy': TableTimeStrategy.FULL_TRACKING,
            'reason': '元数据可能需要补充或修正',
            'fields': ['created_at', 'updated_at']
        },
        
        'api_requests': {
            'strategy': TableTimeStrategy.FULL_TRACKING,
            'reason': 'API请求记录可能需要补充状态、错误信息等',
            'fields': ['created_at', 'updated_at']
        }
    }
    
    # ============ 时间字段操作工具 ============
    
    @staticmethod
    def get_current_utc():
        """获取当前UTC时间（统一接口）"""
        return TimeUtils.utc_now()
    
    @staticmethod
    def format_for_db(dt):
        """格式化时间用于数据库存储"""
        if dt is None:
            return TimeUtils.utc_now()
        return TimeUtils.to_utc(dt)
    
    @staticmethod
    def format_for_api(dt):
        """格式化时间用于API响应"""
        if dt is None:
            return None
        return TimeUtils.format_iso_utc(dt)
    
    # ============ 数据库操作时间处理 ============
    
    @staticmethod
    def prepare_create_data(data_dict):
        """准备创建数据（自动添加created_at和updated_at）"""
        now = TimeUtils.utc_now()
        data_dict[DatabaseTimeStandard.CREATED_AT] = now
        data_dict[DatabaseTimeStandard.UPDATED_AT] = now
        return data_dict
    
    @staticmethod
    def prepare_update_data(data_dict):
        """准备更新数据（自动添加updated_at）"""
        data_dict[DatabaseTimeStandard.UPDATED_AT] = TimeUtils.utc_now()
        return data_dict
    
    # ============ 查询时间范围工具 ============
    
    @staticmethod
    def get_date_range_condition(start_date=None, end_date=None, field_name='created_at'):
        """生成时间范围查询条件"""
        conditions = []
        
        if start_date:
            start_utc = TimeUtils.to_utc(start_date)
            conditions.append(f"{field_name} >= '{start_utc}'")
        
        if end_date:
            end_utc = TimeUtils.to_utc(end_date)
            conditions.append(f"{field_name} <= '{end_utc}'")
        
        return " AND ".join(conditions) if conditions else "1=1"

# ============ 实际应用示例 ============

"""
使用示例：

1. 创建数据时：
data = {'username': 'test', 'email': 'test@example.com'}
data = DatabaseTimeStandard.prepare_create_data(data)
# 自动添加 created_at 和 updated_at

2. 更新数据时：
data = {'email': 'new@example.com'}
data = DatabaseTimeStandard.prepare_update_data(data)
# 自动添加 updated_at

3. 查询时间范围：
from datetime import datetime, timedelta
start_date = datetime.now() - timedelta(days=7)
condition = DatabaseTimeStandard.get_date_range_condition(start_date=start_date)
# 生成: "created_at >= '2025-08-07T00:00:00Z'"

4. API响应格式化：
response_data['created_at'] = DatabaseTimeStandard.format_for_api(row['created_at'])
# 统一格式化为 ISO UTC 字符串
"""

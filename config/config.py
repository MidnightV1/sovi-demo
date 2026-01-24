"""
配置文件
管理应用的环境变量和配置参数
"""

import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

class Config:
    """应用配置类"""
    
    # 应用基本信息
    APP_NAME = "Sovi - 拍照解题助手"
    APP_VERSION = "1.5.2"
    
    # 环境配置
    ENV = os.getenv('ENV', 'development')
    DEBUG = os.getenv('DEBUG', 'True').lower() == 'true'
    LOCAL_DEV = os.getenv('LOCAL_DEV', 'True').lower() == 'true'
    
    # 数据库配置 - 直接使用环境变量
    # 本地默认使用 data/sovi_demo.db，生产建议使用 PostgreSQL
    DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///data/sovi_demo.db' if os.getenv('LOCAL_DEV', 'True').lower() == 'true' else 'postgresql://localhost:5432/sovi_demo')
    
    DB_HOST = os.getenv('DB_HOST', 'localhost')
    DB_PORT = os.getenv('DB_PORT', '5432')
    DB_NAME = os.getenv('DB_NAME', 'sovi_demo')
    DB_USER = os.getenv('DB_USER', 'postgres')
    DB_PASSWORD = os.getenv('DB_PASSWORD', '')
    
    # 数据库类型选择
    USE_POSTGRESQL = os.getenv('USE_POSTGRESQL', 'false').lower() == 'true'
    
    # Google Cloud配置
    PROJECT_ID = os.getenv('PROJECT_ID', 'your-gcp-project-id')
    INSTANCE_CONNECTION_NAME = os.getenv('INSTANCE_CONNECTION_NAME', 'your-project:region:instance-name')
    
    # Gemini API配置
    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', 'your_gemini_api_key_here')
    GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')
    
    # 存储配置
    USE_GCS_STORAGE = os.getenv('USE_GCS_STORAGE', 'false').lower() == 'true'
    GCS_BUCKET_NAME = os.getenv('GCS_BUCKET_NAME', 'sovi-demo-images')
    LOCAL_STORAGE_PATH = os.getenv('LOCAL_STORAGE_PATH', 'temp_image_storage')
    
    # 会话配置
    SESSION_EXPIRY_DAYS = int(os.getenv('SESSION_EXPIRY_DAYS', '7'))
    
    # 文件上传配置
    MAX_FILE_SIZE = int(os.getenv('MAX_FILE_SIZE', '10485760'))  # 10MB
    ALLOWED_IMAGE_TYPES = ['png', 'jpg', 'jpeg']
    
    # 日志配置
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

    # 特性开关（默认启用V2链路，可通过环境变量关闭）
    USE_CHAT_V2 = os.getenv('USE_CHAT_V2', 'true').lower() == 'true'
    USE_WELCOME_V2 = os.getenv('USE_WELCOME_V2', 'true').lower() == 'true'
    
    @classmethod
    def validate_config(cls):
        """验证配置参数"""
        errors = []
        
        # 检查必要的环境变量
        if cls.LOCAL_DEV:
            if not cls.GEMINI_API_KEY:
                errors.append("本地开发环境需要设置 GEMINI_API_KEY")
            if not cls.DATABASE_URL and not (cls.DB_HOST and cls.DB_NAME):
                errors.append("本地开发环境需要设置数据库连接信息")
        else:
            if not cls.PROJECT_ID:
                errors.append("生产环境需要设置 PROJECT_ID")
            if not (cls.DB_HOST and cls.DB_NAME and cls.DB_USER and cls.DB_PASSWORD):
                errors.append("生产环境需要设置数据库连接信息 (DB_HOST, DB_NAME, DB_USER, DB_PASSWORD)")
        
        if errors:
            raise ValueError(f"配置验证失败: {'; '.join(errors)}")
        
        return True
    
    @classmethod
    def get_database_manager(cls):
        """
        根据配置返回合适的数据库管理器
        
        Returns:
            DatabaseManager: SQLite兼容版本或PostgreSQL专用版本
        """
        import logging
        logger = logging.getLogger(__name__)

        # 检查是否强制使用PostgreSQL或有完整的PostgreSQL配置
        has_pg_config = all([cls.DB_HOST, cls.DB_NAME, cls.DB_USER, cls.DB_PASSWORD])

        if cls.USE_POSTGRESQL and has_pg_config:
            try:
                from infrastructure.db.db_postgre import PostgreSQLDatabaseManager
                logger.info("使用PostgreSQL专用数据库管理器")
                return PostgreSQLDatabaseManager()
            except ImportError as e:
                logger.warning(f"PostgreSQL模块导入失败，回退到兼容版本: {e}")
            except Exception as e:
                logger.warning(f"PostgreSQL连接失败，回退到兼容版本: {e}")

        # 默认使用SQLite兼容版本
        from infrastructure.db.db import DatabaseManager
        logger.info("使用SQLite兼容版本数据库管理器")
        return DatabaseManager()

    @classmethod
    def get_database_url(cls):
        """获取数据库连接URL"""
        if cls.LOCAL_DEV:
            return cls.DATABASE_URL
        else:
            # 生产环境使用Cloud SQL连接器
            return None
    
    @classmethod
    def get_gemini_config(cls):
        """获取Gemini配置"""
        return {
            'api_key': cls.GEMINI_API_KEY,
            'model': cls.GEMINI_MODEL,
            'temperature': 0.2,
            'max_output_tokens': 2048
        }

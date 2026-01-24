"""
PostgreSQL专用数据库管理器
基于DB_MIGRATION_ANALYSIS.md的分析，使用PostgreSQL原生语法重写
保持与原DatabaseManager相同的接口，但使用PostgreSQL特性优化实现
"""

import logging
from datetime import datetime, timedelta
from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, Text, Boolean, DateTime, DECIMAL, text
from sqlalchemy.exc import SQLAlchemyError
import os
from config import Config
from tools.utils import TimeUtils
from infrastructure.db.db_time_standard import DatabaseTimeStandard

logger = logging.getLogger(__name__)

class PostgreSQLDatabaseManager:
    """PostgreSQL专用数据库管理器"""
    
    def __init__(self):
        """初始化PostgreSQL数据库管理器"""
        self.engine = None
        self.db_type = "postgresql"  # 明确标识为PostgreSQL
        self._init_connection()
        self._create_tables()
        logger.info("PostgreSQL数据库管理器初始化完成")

    def _init_connection(self):
        """初始化PostgreSQL连接"""
        try:
            # 检查是否使用Cloud SQL连接器
            use_cloud_sql = os.getenv('USE_CLOUD_SQL_CONNECTOR', 'false').lower() == 'true'
            
            if use_cloud_sql:
                # 使用Cloud SQL连接器的Unix socket连接
                instance_connection_name = os.getenv('INSTANCE_CONNECTION_NAME')
                db_socket_dir = os.getenv('DB_SOCKET_DIR', '/cloudsql')
                db_name = Config.DB_NAME
                db_user = Config.DB_USER
                db_password = Config.DB_PASSWORD
                
                # 使用psycopg2驱动，更好支持Cloud SQL连接器
                connection_string = f"postgresql+psycopg2://{db_user}:{db_password}@/{db_name}?host={db_socket_dir}/{instance_connection_name}"
                logger.info(f"使用Cloud SQL连接器Unix socket连接: {db_socket_dir}/{instance_connection_name}")
            else:
                # 传统TCP连接
                db_host = Config.DB_HOST
                db_port = Config.DB_PORT or 5432
                db_name = Config.DB_NAME
                db_user = Config.DB_USER
                db_password = Config.DB_PASSWORD
                
                # PostgreSQL连接字符串 - 使用psycopg2驱动
                connection_string = f"postgresql+psycopg2://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
                logger.info("使用传统TCP PostgreSQL连接")
            
            # 创建引擎，配置PostgreSQL特定参数
            self.engine = create_engine(
                connection_string,
                pool_size=3,          # 减少连接池大小适应Cloud Run
                max_overflow=1,       # 减少溢出连接
                pool_timeout=30,
                pool_recycle=1800,
                pool_pre_ping=True,   # 添加连接检测
                echo=False  # 生产环境关闭SQL日志
            )
            
            # 测试连接
            with self.engine.connect() as conn:
                result = conn.execute(text("SELECT version()"))
                version_info = result.fetchone()[0]
                logger.info(f"PostgreSQL连接成功: {version_info}")
                
        except Exception as e:
            logger.error(f"PostgreSQL连接失败: {str(e)}")
            raise

    def _create_tables(self):
        """创建PostgreSQL表结构"""
        try:
            self._create_base_tables()
            self._create_database_indexes()
            self._check_and_migrate_data_types()  # 新增：检查并执行数据类型迁移
            logger.info("PostgreSQL表结构创建完成")
        except Exception as e:
            logger.error(f"创建表结构失败: {str(e)}")
            raise

    def _create_base_tables(self):
        """创建基础表结构 - PostgreSQL版本"""
        try:
            metadata = MetaData()
            
            # users表 - 用户基础信息
            Table('users', metadata,
                Column('user_id', Integer, primary_key=True, autoincrement=True),
                Column('username', String(255), unique=True, nullable=False),
                Column('hashed_password', String(255), nullable=False),
                DatabaseTimeStandard.get_created_at_column(),
                DatabaseTimeStandard.get_updated_at_column(),
                extend_existing=True
            )
            
            # user_sessions表 - 用户会话管理
            Table('user_sessions', metadata,
                Column('session_id', String(36), primary_key=True),
                Column('user_id', Integer, nullable=False),
                Column('expires_at', DateTime, nullable=False),
                DatabaseTimeStandard.get_created_at_column(),
                DatabaseTimeStandard.get_updated_at_column(),
                extend_existing=True
            )
            
            # conversations表 - 对话管理（支持软删除）
            Table('conversations', metadata,
                Column('conversation_id', Integer, primary_key=True, autoincrement=True),
                Column('user_id', Integer, nullable=False),
                Column('title', String(255), nullable=False),
                Column('is_deleted', Boolean, default=False, nullable=False),
                Column('deleted_at', DateTime, nullable=True),
                DatabaseTimeStandard.get_created_at_column(),
                DatabaseTimeStandard.get_updated_at_column(),
                extend_existing=True
            )
            
            # messages表 - 消息存储（核心表）
            Table('messages', metadata,
                Column('message_id', Integer, primary_key=True, autoincrement=True),
                Column('conversation_id', Integer, nullable=True),  # 支持独立欢迎消息
                Column('user_id', Integer, nullable=False),
                Column('role', String(50), nullable=False),  # user/assistant/server
                Column('round_num', Integer, nullable=False, default=0),  # 轮次编号
                Column('origin_content', Text, nullable=False),  # 原始输入
                Column('view_content', Text),  # 展示内容
                Column('working_content', Text),  # 工作内容
                Column('content_summary', Text),  # 内容摘要
                Column('action_mode', String(20)),  # 处理模式
                Column('is_valid_question', Boolean),  # 问题有效性
                Column('image_url', String(1024)),  # 图片URL
                Column('api_request_id', String(100)),  # 关联API请求记录ID
                Column('metadata_id', Integer),  # 关联question_metadata表ID
                Column('send_status', String(20), default='success'),  # 消息发送状态
                DatabaseTimeStandard.get_created_at_column(),
                DatabaseTimeStandard.get_updated_at_column(),
                extend_existing=True
            )

            # api_requests表 - API请求日志（解耦设计）
            Table('api_requests', metadata,
                Column('id', Integer, primary_key=True, autoincrement=True),
                Column('request_id', String(100), unique=True, nullable=False),
                Column('user_id', Integer, nullable=False),
                Column('conversation_id', Integer, nullable=True),
                Column('message_id', Integer, nullable=True),
                Column('session_context', String(200)),  # 会话上下文
                Column('request_type', String(50)),  # 请求类型
                Column('has_current_image', Boolean),  # 是否包含图片
                
                # 缓存相关字段
                Column('used_cache', Boolean, default=False),
                Column('cache_name', String(255)),
                Column('cached_tokens', Integer),
                Column('cache_cost_usd', DECIMAL(12, 6), default=0.0),
                Column('cache_cost_cny', DECIMAL(12, 4), default=0.0),
                
                # 请求数据
                Column('request_data', Text),  # 完整的API请求JSON数据
                Column('image_data_info', Text),  # 图片信息
                
                # 响应数据
                Column('raw_response', Text),  # 模型原始响应
                Column('response_meta', Text),  # 响应元数据
                
                # Token和成本数据
                Column('model_name', String(50)),
                Column('input_tokens', Integer),
                Column('output_tokens', Integer), 
                Column('total_tokens', Integer),
                Column('input_cost_usd', DECIMAL(12, 6), default=0.0),
                Column('output_cost_usd', DECIMAL(12, 6), default=0.0),
                Column('total_cost_usd', DECIMAL(12, 6), default=0.0),
                Column('total_cost_cny', DECIMAL(12, 4), default=0.0),
                
                # 时间和性能数据
                Column('request_start_time', DateTime),
                Column('first_token_time_ms', Integer),  # 首token耗时（毫秒）
                Column('user_visible_time_ms', Integer),  # 用户感知耗时（毫秒）
                Column('completion_time', DateTime),
                Column('total_duration_ms', Integer),
                
                # 错误和状态
                Column('status', String(20)),  # success, error, timeout
                Column('error_message', Text),
                Column('retry_count', Integer, default=0),
                
                DatabaseTimeStandard.get_created_at_column(),
                DatabaseTimeStandard.get_updated_at_column(),
                extend_existing=True
            )
            
            # system_cache_status表 - 系统缓存状态管理
            Table('system_cache_status', metadata,
                Column('id', Integer, primary_key=True, autoincrement=True),
                Column('model_name', String(100), unique=True, nullable=False),
                Column('api_cache_name', String(255), nullable=False),
                Column('system_instruction_hash', String(64)),
                Column('token_count', Integer),
                Column('expire_time', DateTime),
                Column('last_used', DateTime),
                Column('usage_count', Integer, default=0),
                Column('cache_cost_usd', DECIMAL(12, 6), default=0.0),
                Column('cache_cost_cny', DECIMAL(12, 4), default=0.0),
                Column('total_saved_usd', DECIMAL(12, 6), default=0.0),
                Column('total_saved_cny', DECIMAL(12, 4), default=0.0),
                DatabaseTimeStandard.get_created_at_column(),
                DatabaseTimeStandard.get_updated_at_column(),
                extend_existing=True
            )

            # question_metadata表 - 问题元数据
            Table('question_metadata', metadata,
                Column('metadata_id', Integer, primary_key=True, autoincrement=True),
                Column('message_id', Integer, nullable=False),
                Column('subject', String(50)),  # 学科
                Column('complexity', String(20)),  # 复杂度
                Column('concepts', Text),  # 概念列表
                Column('question_type', String(50)),  # 问题类型
                Column('difficulty_level', String(20)),  # 难度等级
                Column('full_xml_content', Text),  # 完整的question_meta XML
                DatabaseTimeStandard.get_created_at_column(),
                DatabaseTimeStandard.get_updated_at_column(),
                extend_existing=True
            )
            
            # user_profiles表 - 用户画像（版本化）
            Table('user_profiles', metadata,
                Column('profile_id', Integer, primary_key=True, autoincrement=True),
                Column('user_id', Integer, nullable=False),
                Column('profile_content', Text, nullable=False),  # 完整markdown
                Column('in_use', Boolean, default=True, nullable=False),  # 是否为当前使用版本
                DatabaseTimeStandard.get_created_at_column(),
                DatabaseTimeStandard.get_updated_at_column(),
                extend_existing=True
            )
            
            # 创建表
            metadata.create_all(self.engine)
            logger.info("PostgreSQL基础数据库表创建成功")
            
        except Exception as e:
            logger.error(f"创建PostgreSQL基础数据库表失败: {str(e)}")
            raise

    def _create_database_indexes(self):
        """创建PostgreSQL数据库索引"""
        try:
            indexes = [
                # 用户相关索引
                "CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)",
                "CREATE INDEX IF NOT EXISTS idx_user_sessions_user_id ON user_sessions(user_id)",
                "CREATE INDEX IF NOT EXISTS idx_user_sessions_expires_at ON user_sessions(expires_at)",
                
                # 对话相关索引
                "CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id)",
                "CREATE INDEX IF NOT EXISTS idx_conversations_is_deleted ON conversations(is_deleted)",
                "CREATE INDEX IF NOT EXISTS idx_conversations_created_at ON conversations(created_at)",
                
                # 消息相关索引
                "CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON messages(conversation_id)",
                "CREATE INDEX IF NOT EXISTS idx_messages_user_id ON messages(user_id)",
                "CREATE INDEX IF NOT EXISTS idx_messages_round_num ON messages(round_num)",
                "CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at)",
                "CREATE INDEX IF NOT EXISTS idx_messages_send_status ON messages(send_status)",
                
                # API请求相关索引
                "CREATE INDEX IF NOT EXISTS idx_api_requests_request_id ON api_requests(request_id)",
                "CREATE INDEX IF NOT EXISTS idx_api_requests_user_id ON api_requests(user_id)",
                "CREATE INDEX IF NOT EXISTS idx_api_requests_conversation_id ON api_requests(conversation_id)",
                "CREATE INDEX IF NOT EXISTS idx_api_requests_created_at ON api_requests(created_at)",
                
                # 缓存相关索引
                "CREATE INDEX IF NOT EXISTS idx_system_cache_model_name ON system_cache_status(model_name)",
                "CREATE INDEX IF NOT EXISTS idx_system_cache_expire_time ON system_cache_status(expire_time)",
                
                # 元数据相关索引
                "CREATE INDEX IF NOT EXISTS idx_question_metadata_message_id ON question_metadata(message_id)",
                "CREATE INDEX IF NOT EXISTS idx_user_profiles_user_id ON user_profiles(user_id)",
                "CREATE INDEX IF NOT EXISTS idx_user_profiles_in_use ON user_profiles(in_use)",
                
                # 复合索引优化
                "CREATE INDEX IF NOT EXISTS idx_messages_user_conversation ON messages(user_id, conversation_id)",
                "CREATE INDEX IF NOT EXISTS idx_messages_user_round ON messages(user_id, round_num)",
                "CREATE INDEX IF NOT EXISTS idx_conversations_user_deleted ON conversations(user_id, is_deleted)",
                
                # 新增性能优化索引
                "CREATE INDEX IF NOT EXISTS idx_messages_conv_created_round ON messages(conversation_id, created_at, round_num)",
                "CREATE INDEX IF NOT EXISTS idx_api_requests_cost_analysis ON api_requests(user_id, created_at, total_cost_usd)",
                "CREATE INDEX IF NOT EXISTS idx_messages_user_today ON messages(user_id, created_at) WHERE role = 'user'",
            ]
            
            with self.engine.connect() as conn:
                for index_sql in indexes:
                    try:
                        conn.execute(text(index_sql))
                        logger.debug(f"索引创建成功: {index_sql}")
                    except Exception as e:
                        logger.warning(f"索引创建失败或已存在: {index_sql}, 错误: {str(e)}")
                
                conn.commit()
                
            logger.info("PostgreSQL数据库索引创建完成")
            
        except Exception as e:
            logger.error(f"创建PostgreSQL数据库索引失败: {str(e)}")
            raise

    def _check_and_migrate_data_types(self):
        """检查并执行数据类型迁移"""
        try:
            with self.engine.connect() as conn:
                # 检查成本字段的数据类型
                result = conn.execute(text("""
                    SELECT column_name, data_type
                    FROM information_schema.columns 
                    WHERE table_name = 'api_requests' 
                      AND column_name IN ('cache_cost_usd', 'total_cost_usd')
                """))
                
                current_types = {row[0]: row[1] for row in result.fetchall()}
                
                # 如果检测到String类型，执行迁移
                if any('character varying' in dtype or 'text' in dtype 
                       for dtype in current_types.values()):
                    logger.info("检测到String类型的成本字段，开始执行数据类型迁移...")
                    self._execute_cost_field_migration(conn)
                else:
                    logger.info("成本字段数据类型已优化，无需迁移")
                    
        except Exception as e:
            logger.warning(f"数据类型检查失败: {str(e)}")

    def _execute_cost_field_migration(self, conn):
        """执行成本字段数据类型迁移"""
        try:
            logger.info("开始迁移api_requests表的成本字段...")
            
            # 迁移api_requests表
            conn.execute(text("""
                ALTER TABLE api_requests 
                  ALTER COLUMN cache_cost_usd TYPE DECIMAL(12, 6) USING 
                    CASE 
                      WHEN cache_cost_usd IS NULL OR cache_cost_usd = '' THEN 0.0
                      ELSE cache_cost_usd::decimal 
                    END,
                  ALTER COLUMN cache_cost_cny TYPE DECIMAL(12, 4) USING 
                    CASE 
                      WHEN cache_cost_cny IS NULL OR cache_cost_cny = '' THEN 0.0
                      ELSE cache_cost_cny::decimal 
                    END,
                  ALTER COLUMN input_cost_usd TYPE DECIMAL(12, 6) USING 
                    CASE 
                      WHEN input_cost_usd IS NULL OR input_cost_usd = '' THEN 0.0
                      ELSE input_cost_usd::decimal 
                    END,
                  ALTER COLUMN output_cost_usd TYPE DECIMAL(12, 6) USING 
                    CASE 
                      WHEN output_cost_usd IS NULL OR output_cost_usd = '' THEN 0.0
                      ELSE output_cost_usd::decimal 
                    END,
                  ALTER COLUMN total_cost_usd TYPE DECIMAL(12, 6) USING 
                    CASE 
                      WHEN total_cost_usd IS NULL OR total_cost_usd = '' THEN 0.0
                      ELSE total_cost_usd::decimal 
                    END,
                  ALTER COLUMN total_cost_cny TYPE DECIMAL(12, 4) USING 
                    CASE 
                      WHEN total_cost_cny IS NULL OR total_cost_cny = '' THEN 0.0
                      ELSE total_cost_cny::decimal 
                    END
            """))
            logger.info("api_requests表迁移完成")
            
            # 检查system_cache_status表是否存在
            result = conn.execute(text("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables 
                    WHERE table_name = 'system_cache_status'
                )
            """))
            
            if result.fetchone()[0]:
                logger.info("开始迁移system_cache_status表的成本字段...")
                conn.execute(text("""
                    ALTER TABLE system_cache_status
                      ALTER COLUMN cache_cost_usd TYPE DECIMAL(12, 6) USING 
                        CASE 
                          WHEN cache_cost_usd IS NULL OR cache_cost_usd = '' THEN 0.0
                          ELSE cache_cost_usd::decimal 
                        END,
                      ALTER COLUMN cache_cost_cny TYPE DECIMAL(12, 4) USING 
                        CASE 
                          WHEN cache_cost_cny IS NULL OR cache_cost_cny = '' THEN 0.0
                          ELSE cache_cost_cny::decimal 
                        END,
                      ALTER COLUMN total_saved_usd TYPE DECIMAL(12, 6) USING 
                        CASE 
                          WHEN total_saved_usd IS NULL OR total_saved_usd = '' THEN 0.0
                          ELSE total_saved_usd::decimal 
                        END,
                      ALTER COLUMN total_saved_cny TYPE DECIMAL(12, 4) USING 
                        CASE 
                          WHEN total_saved_cny IS NULL OR total_saved_cny = '' THEN 0.0
                          ELSE total_saved_cny::decimal 
                        END
                """))
                logger.info("system_cache_status表迁移完成")
            
            conn.commit()
            logger.info("数据类型迁移全部完成")
            
        except Exception as e:
            logger.error(f"数据类型迁移失败: {str(e)}")
            conn.rollback()
            raise

    # ============ 用户管理类方法 ============
    
    def get_user_by_username(self, username):
        """根据用户名获取用户信息"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("SELECT user_id, username, hashed_password, created_at FROM users WHERE username = :username"),
                    {"username": username}
                )
                
                row = result.fetchone()
                if row:
                    return {
                        'user_id': row[0],
                        'username': row[1],
                        'hashed_password': row[2],
                        'created_at': row[3]
                    }
                return None
                
        except Exception as e:
            logger.error(f"获取用户信息失败: {str(e)}")
            return None

    def create_user(self, username, hashed_password):
        """创建新用户 - PostgreSQL版本使用RETURNING获取ID"""
        try:
            now_utc = TimeUtils.utc_now()
            
            with self.engine.connect() as conn:
                # PostgreSQL使用RETURNING子句获取新插入的ID
                result = conn.execute(
                    text("""
                        INSERT INTO users (username, hashed_password, created_at, updated_at) 
                        VALUES (:username, :hashed_password, :created_at, :updated_at)
                        RETURNING user_id
                    """),
                    {
                        "username": username,
                        "hashed_password": hashed_password,
                        "created_at": now_utc,
                        "updated_at": now_utc
                    }
                )
                
                user_id = result.fetchone()[0]
                conn.commit()
                
                logger.info(f"用户创建成功: {username}, ID: {user_id}")
                return user_id
                
        except Exception as e:
            logger.error(f"创建用户失败: {str(e)}")
            return None

    def get_user_by_id(self, user_id):
        """根据用户ID获取用户信息"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("SELECT user_id, username, created_at FROM users WHERE user_id = :user_id"),
                    {"user_id": user_id}
                )
                
                row = result.fetchone()
                if row:
                    return {
                        'user_id': row[0],
                        'username': row[1],
                        'created_at': row[2]
                    }
                return None
                
        except Exception as e:
            logger.error(f"获取用户信息失败: {str(e)}")
            return None

    # ============ 会话管理类方法 ============
    
    def create_session(self, session_id, user_id, expires_at):
        """创建用户会话"""
        try:
            now_utc = TimeUtils.utc_now()
            
            with self.engine.connect() as conn:
                conn.execute(
                    text("""
                        INSERT INTO user_sessions (session_id, user_id, expires_at, created_at, updated_at)
                        VALUES (:session_id, :user_id, :expires_at, :created_at, :updated_at)
                    """),
                    {
                        "session_id": session_id,
                        "user_id": user_id,
                        "expires_at": expires_at,
                        "created_at": now_utc,
                        "updated_at": now_utc
                    }
                )
                
                conn.commit()
                logger.info(f"会话创建成功: {session_id}, 用户: {user_id}")
                return True
                
        except Exception as e:
            logger.error(f"创建会话失败: {str(e)}")
            return False

    def get_session(self, session_id):
        """获取会话信息"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT session_id, user_id, expires_at, created_at 
                        FROM user_sessions 
                        WHERE session_id = :session_id
                    """),
                    {"session_id": session_id}
                )
                
                row = result.fetchone()
                if row:
                    return {
                        'session_id': row[0],
                        'user_id': row[1],
                        'expires_at': row[2],
                        'created_at': row[3]
                    }
                return None
                
        except Exception as e:
            logger.error(f"获取会话信息失败: {str(e)}")
            return None

    def get_valid_sessions(self):
        """获取所有有效会话 - PostgreSQL版本使用NOW()"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT session_id, user_id, expires_at 
                        FROM user_sessions 
                        WHERE expires_at > NOW()
                        ORDER BY created_at DESC
                    """)
                )
                
                sessions = []
                for row in result.fetchall():
                    sessions.append({
                        'session_id': row[0],
                        'user_id': row[1],
                        'expires_at': row[2]
                    })
                
                return sessions
                
        except Exception as e:
            logger.error(f"获取有效会话失败: {str(e)}")
            return []

    def delete_session(self, session_id):
        """删除会话"""
        try:
            with self.engine.connect() as conn:
                conn.execute(
                    text("DELETE FROM user_sessions WHERE session_id = :session_id"),
                    {"session_id": session_id}
                )
                
                conn.commit()
                logger.info(f"会话删除成功: {session_id}")
                return True
                
        except Exception as e:
            logger.error(f"删除会话失败: {str(e)}")
            return False

    def get_active_session_by_user_id(self, user_id):
        """获取用户的活跃会话 - PostgreSQL版本使用NOW()"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT session_id, user_id, expires_at, created_at 
                        FROM user_sessions 
                        WHERE user_id = :user_id AND expires_at > NOW()
                        ORDER BY created_at DESC 
                        LIMIT 1
                    """),
                    {"user_id": user_id}
                )
                
                row = result.fetchone()
                if row:
                    return {
                        'session_id': row[0],
                        'user_id': row[1],
                        'expires_at': row[2],
                        'created_at': row[3]
                    }
                return None
                
        except Exception as e:
            logger.error(f"获取用户活跃会话失败: {str(e)}")
            return None

    # ============ 对话管理类方法 ============
    
    def get_user_conversations(self, user_id, limit=50):
        """获取用户对话列表"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT conversation_id, title, created_at, updated_at
                        FROM conversations 
                        WHERE user_id = :user_id AND is_deleted = FALSE
                        ORDER BY updated_at DESC 
                        LIMIT :limit
                    """),
                    {"user_id": user_id, "limit": limit}
                )
                
                conversations = []
                for row in result.fetchall():
                    conversations.append({
                        'conversation_id': row[0],
                        'title': row[1],
                        'created_at': row[2],
                        'updated_at': row[3]
                    })
                
                return conversations
                
        except Exception as e:
            logger.error(f"获取用户对话列表失败: {str(e)}")
            return []

    def create_conversation(self, user_id, title):
        """创建新对话 - PostgreSQL版本使用RETURNING获取ID"""
        try:
            now_utc = TimeUtils.utc_now()
            
            with self.engine.connect() as conn:
                # PostgreSQL使用RETURNING子句获取新插入的ID
                result = conn.execute(
                    text("""
                        INSERT INTO conversations (user_id, title, is_deleted, created_at, updated_at)
                        VALUES (:user_id, :title, FALSE, :created_at, :updated_at)
                        RETURNING conversation_id
                    """),
                    {
                        "user_id": user_id,
                        "title": title,
                        "created_at": now_utc,
                        "updated_at": now_utc
                    }
                )
                
                conversation_id = result.fetchone()[0]
                conn.commit()
                
                logger.info(f"对话创建成功: {title}, ID: {conversation_id}, 用户: {user_id}")
                return conversation_id
                
        except Exception as e:
            logger.error(f"创建对话失败: {str(e)}")
            return None

    def get_conversation_messages(self, conversation_id):
        """获取对话消息 - 优化版：单次查询合并对话检查和消息获取"""
        try:
            with self.engine.connect() as conn:
                # 使用 EXISTS 子查询来验证对话的有效性，并在一次查询中获取所有消息
                result = conn.execute(
                    text("""
                        SELECT m.message_id, m.role, m.origin_content, m.view_content, m.working_content, 
                               m.image_url, m.send_status, m.created_at
                        FROM messages m
                        WHERE m.conversation_id = :conversation_id 
                          AND EXISTS (
                              SELECT 1 FROM conversations c
                              WHERE c.conversation_id = m.conversation_id AND c.is_deleted = FALSE
                          )
                        ORDER BY m.created_at ASC
                    """),
                    {"conversation_id": conversation_id}
                )
                
                messages = []
                for row in result.fetchall():
                    messages.append({
                        'message_id': row[0],
                        'role': row[1],
                        'origin_content': row[2],
                        'view_content': row[3],
                        'working_content': row[4],
                        'image_url': row[5],
                        'send_status': row[6],
                        'created_at': row[7]
                    })
                
                # 如果没有消息，说明对话不存在或已删除
                if not messages:
                    # 再次检查对话是否存在（用于日志记录）
                    conv_check = conn.execute(
                        text("SELECT conversation_id FROM conversations WHERE conversation_id = :conv_id"),
                        {"conv_id": conversation_id}
                    )
                    if not conv_check.fetchone():
                        logger.warning(f"对话 {conversation_id} 不存在")
                    else:
                        logger.warning(f"对话 {conversation_id} 已被删除或无消息")
                
                return messages
                
        except Exception as e:
            logger.error(f"获取对话消息失败: {str(e)}")
            return []

    # ============ 消息管理类方法 ============
    
    def save_message(self, conversation_id, role, origin_content, round_num=0, 
                     view_content=None, working_content=None, content_summary=None, 
                     action_mode=None, question_meta=None, is_valid_question=None, 
                     image_url=None, api_request_id=None, user_id=None, send_status='success'):
        """保存消息 (新版本 - 支持表拆分架构和独立欢迎消息) - PostgreSQL版本"""
        try:
            with self.engine.connect() as conn:
                with conn.begin():  # 使用显式事务
                    # 准备消息数据
                    now_utc = TimeUtils.utc_now()
                    message_data = {
                        "conversation_id": conversation_id,  # 对于独立欢迎消息可能为None
                        "user_id": user_id,  # 新增必填字段
                        "role": role,
                        "round_num": round_num,
                        "origin_content": origin_content,
                        "view_content": view_content,
                        "working_content": working_content,
                        "content_summary": content_summary,
                        "action_mode": action_mode,
                        "is_valid_question": is_valid_question,
                        "image_url": image_url,
                        "api_request_id": api_request_id,
                        "send_status": send_status,
                        "created_at": now_utc,
                        "updated_at": now_utc
                    }
                    
                    # PostgreSQL使用RETURNING子句获取新插入的ID
                    result = conn.execute(
                        text("""
                            INSERT INTO messages (conversation_id, user_id, role, round_num, origin_content, view_content, 
                                                working_content, content_summary, action_mode, 
                                                is_valid_question, image_url, api_request_id, send_status, created_at, updated_at)
                            VALUES (:conversation_id, :user_id, :role, :round_num, :origin_content, :view_content, 
                                   :working_content, :content_summary, :action_mode, 
                                   :is_valid_question, :image_url, :api_request_id, :send_status, :created_at, :updated_at)
                            RETURNING message_id
                        """),
                        message_data
                    )
                    message_id = result.fetchone()[0]
                    
                    # 如果有问题元数据，保存到元数据表
                    metadata_id = None
                    if question_meta:
                        metadata_id = self._save_question_metadata(conn, message_id, question_meta)
                        
                        # 更新消息记录的metadata_id
                        if metadata_id:
                            conn.execute(
                                text("UPDATE messages SET metadata_id = :metadata_id WHERE message_id = :message_id"),
                                {"metadata_id": metadata_id, "message_id": message_id}
                            )
                    
                    logger.info(f"消息保存成功: ID={message_id}, 角色={role}, 轮次={round_num}, 用户={user_id}")
                    return message_id
                    
        except Exception as e:
            logger.error(f"保存消息失败: {str(e)}")
            return None

    def get_user_welcome_message(self, user_id, window_minutes=30):
        """获取用户最新的独立欢迎消息（round_num=-1），按整点和整半小时对齐的时间窗口"""
        try:
            with self.engine.connect() as conn:
                # 计算当前整点或整半小时对齐的时间窗口开始时间
                now_result = conn.execute(text("SELECT NOW()"))
                current_time = now_result.scalar()
                
                # 对齐到整点或整半小时
                aligned_minute = 0 if current_time.minute < 30 else 30
                aligned_time = current_time.replace(minute=aligned_minute, second=0, microsecond=0)
                
                result = conn.execute(
                    text("""
                        SELECT message_id, origin_content, view_content, working_content, created_at
                        FROM messages 
                        WHERE user_id = :user_id 
                          AND role = 'server' 
                          AND round_num = -1 
                          AND created_at >= :window_start
                        ORDER BY created_at DESC 
                        LIMIT 1
                    """),
                    {"user_id": user_id, "window_start": aligned_time}
                )
                row = result.fetchone()
                if row:
                    return {
                        'message_id': row[0],
                        'origin_content': row[1],
                        'view_content': row[2],
                        'working_content': row[3],
                        'created_at': row[4]
                    }
                return None
        except Exception as e:
            logger.error(f"获取用户欢迎消息失败: {str(e)}")
            return None

    def update_welcome_message_to_active(self, message_id, conversation_id):
        """将欢迎消息更新为激活状态"""
        try:
            now_utc = TimeUtils.utc_now()
            
            with self.engine.connect() as conn:
                conn.execute(
                    text("""
                        UPDATE messages 
                        SET conversation_id = :conversation_id, 
                            round_num = 0, 
                            updated_at = :updated_at
                        WHERE message_id = :message_id
                    """),
                    {
                        "conversation_id": conversation_id,
                        "message_id": message_id,
                        "updated_at": now_utc
                    }
                )
                
                conn.commit()
                logger.info(f"欢迎消息激活成功: {message_id} -> 对话: {conversation_id}")
                return True
                
        except Exception as e:
            logger.error(f"激活欢迎消息失败: {str(e)}")
            return False

    def update_message_status(self, message_id: int, send_status: str) -> bool:
        """更新消息发送状态"""
        try:
            now_utc = TimeUtils.utc_now()
            
            with self.engine.connect() as conn:
                conn.execute(
                    text("UPDATE messages SET send_status = :send_status, updated_at = :updated_at WHERE message_id = :message_id"),
                    {
                        "send_status": send_status,
                        "updated_at": now_utc,
                        "message_id": message_id
                    }
                )
                conn.commit()
                logger.info(f"消息状态已更新: message_id={message_id}, status={send_status}")
                return True
        except Exception as e:
            logger.error(f"更新消息状态失败: {str(e)}")
            return False

    def get_message_by_id(self, message_id: int) -> dict:
        """根据消息ID获取消息详情"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT message_id, conversation_id, user_id, role, round_num, 
                               origin_content, view_content, working_content, image_url, 
                               send_status, created_at, updated_at
                        FROM messages 
                        WHERE message_id = :message_id
                    """),
                    {"message_id": message_id}
                )
                row = result.fetchone()
                if row:
                    return {
                        'message_id': row[0],
                        'conversation_id': row[1],
                        'user_id': row[2],
                        'role': row[3],
                        'round_num': row[4],
                        'origin_content': row[5],
                        'view_content': row[6],
                        'working_content': row[7],
                        'image_url': row[8],
                        'send_status': row[9],
                        'created_at': row[10],
                        'updated_at': row[11]
                    }
                return None
        except Exception as e:
            logger.error(f"获取消息失败: {str(e)}")
            return None

    def update_conversation_title(self, conversation_id, title):
        """更新对话标题"""
        try:
            with self.engine.connect() as conn:
                conn.execute(
                    text("UPDATE conversations SET title = :title, updated_at = :updated_at WHERE conversation_id = :conversation_id"),
                    {"conversation_id": conversation_id, "title": title, "updated_at": TimeUtils.utc_now()}
                )
                conn.commit()
        except Exception as e:
            logger.error(f"更新对话标题失败: {str(e)}")
            raise

    def get_conversation_title(self, conversation_id):
        """获取指定对话当前标题"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("SELECT title FROM conversations WHERE conversation_id = :conversation_id"),
                    {"conversation_id": conversation_id}
                )
                row = result.fetchone()
                if row:
                    return row[0]
                return None
        except Exception as e:
            logger.error(f"获取对话标题失败: {str(e)}")
            return None
    
    def delete_conversation(self, conversation_id, user_id):
        """软删除对话（只标记为已删除）"""
        try:
            with self.engine.connect() as conn:
                # 首先检查对话是否属于该用户
                result = conn.execute(
                    text("SELECT user_id FROM conversations WHERE conversation_id = :conversation_id"),
                    {"conversation_id": conversation_id}
                )
                row = result.fetchone()
                
                if not row:
                    logger.warning(f"对话 {conversation_id} 不存在")
                    return False
                    
                if row[0] != user_id:
                    logger.warning(f"用户 {user_id} 无权删除对话 {conversation_id}")
                    return False
                
                # 执行软删除
                conn.execute(
                    text("""
                        UPDATE conversations 
                        SET is_deleted = TRUE, deleted_at = :deleted_at, updated_at = :updated_at 
                        WHERE conversation_id = :conversation_id
                    """),
                    {
                        "conversation_id": conversation_id, 
                        "deleted_at": TimeUtils.utc_now(),
                        "updated_at": TimeUtils.utc_now()
                    }
                )
                conn.commit()
                logger.info(f"对话已软删除: {conversation_id}")
                return True
                
        except Exception as e:
            logger.error(f"删除对话失败: {str(e)}")
            return False

    def _save_question_metadata(self, conn, message_id, question_meta_xml):
        """保存问题元数据到独立表 - PostgreSQL版本"""
        try:
            # 解析XML提取结构化数据
            metadata = self._parse_question_meta_xml(question_meta_xml)
            
            # 准备元数据
            now_utc = TimeUtils.utc_now()
            metadata_with_time = {
                "message_id": message_id,
                "subject": metadata.get('subject'),
                "complexity": metadata.get('complexity'),
                "concepts": metadata.get('concepts'),
                "question_type": metadata.get('question_type'),
                "difficulty_level": metadata.get('difficulty_level'),
                "full_xml_content": question_meta_xml,
                "created_at": now_utc,
                "updated_at": now_utc
            }
            
            # PostgreSQL使用RETURNING子句获取新插入的ID
            result = conn.execute(
                text("""
                    INSERT INTO question_metadata 
                    (message_id, subject, complexity, concepts, question_type, difficulty_level, full_xml_content, created_at, updated_at)
                    VALUES (:message_id, :subject, :complexity, :concepts, :question_type, :difficulty_level, :full_xml_content, :created_at, :updated_at)
                    RETURNING metadata_id
                """),
                metadata_with_time
            )
            return result.fetchone()[0]
                
        except Exception as e:
            logger.error(f"保存问题元数据失败: {str(e)}")
            return None

    def _parse_question_meta_xml(self, xml_content):
        """解析问题元数据XML"""
        try:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(xml_content)
            
            return {
                'subject': self._get_xml_text(root, 'Subject'),
                'complexity': self._get_xml_text(root, 'Complexity'),  
                'concepts': self._get_xml_text(root, 'Concepts'),
                'question_type': self._get_xml_text(root, 'Question_Type'),
                'difficulty_level': self._get_xml_text(root, 'Difficulty_Level')
            }
        except Exception as e:
            logger.error(f"解析问题元数据XML失败: {str(e)}")
            return {}

    def _get_xml_text(self, root, tag_name):
        """获取XML标签文本"""
        element = root.find(tag_name)
        return element.text.strip() if element is not None and element.text else ""

    def get_conversation_history(self, conversation_id, limit=20):
        """获取对话历史，用于构建多轮对话上下文，排除发送失败的消息"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT message_id, role, working_content, image_url, round_num, created_at
                        FROM messages 
                        WHERE conversation_id = :conversation_id AND (send_status IS NULL OR send_status = 'success')
                        ORDER BY created_at ASC, round_num ASC
                        LIMIT :limit
                    """),
                    {"conversation_id": conversation_id, "limit": limit}
                )
                
                history = []
                for row in result.fetchall():
                    history.append({
                        'message_id': row[0],
                        'role': row[1],
                        'working_content': row[2],
                        'image_url': row[3],
                        'round_num': row[4],
                        'created_at': row[5]
                    })
                
                return history
                
        except Exception as e:
            logger.error(f"获取对话历史失败: {str(e)}")
            return []

    def save_api_request_log(self, request_data):
        """
        保存API请求日志（解耦版本）- PostgreSQL版本
        
        Args:
            request_data: dict，包含以下字段：
                - request_id: 请求ID（UUID）
                - user_id: 用户ID（必须）
                - conversation_id: 对话ID（可选）
                - message_id: 消息ID（可选）
                - session_context: 会话上下文（如welcome_generation, normal_chat）
                - request_type: 请求类型（如'gemini_text'）
                - model_name: 模型名称
                - request_data: 完整的API请求JSON数据
                - raw_response: 模型原始响应
                - response_meta: 最后一个chunk的完整信息（JSON字符串）
                - input_tokens: 输入token数量
                - output_tokens: 输出token数量
                - request_start_time: 请求开始时间
                - first_token_time_ms: 第一个token耗时（毫秒）
                - user_visible_time_ms: 用户感知首token耗时（毫秒）
                - completion_time: 完成时间
                - status: 状态（success/error）
                - error_message: 错误信息（可选）
                
        Returns:
            str: 请求ID，失败返回None
        """
        try:
            from tools.cost_calculator import CostCalculator
            
            request_id = request_data.get('request_id')
            if not request_id:
                import uuid
                request_id = str(uuid.uuid4())
            
            # 计算成本
            cost_info = CostCalculator.calculate_cost(
                request_data.get('model_name', '2.5-Flash'),
                request_data.get('input_tokens', 0),
                request_data.get('output_tokens', 0),
                cached_tokens=request_data.get('cached_tokens', 0)
            )
            
            # 计算时长
            duration_ms = None
            if request_data.get('request_start_time') and request_data.get('completion_time'):
                start = request_data['request_start_time']
                end = request_data['completion_time']
                if isinstance(start, str):
                    start = datetime.fromisoformat(start.replace('Z', '+00:00'))
                if isinstance(end, str):
                    end = datetime.fromisoformat(end.replace('Z', '+00:00'))
                duration_ms = int((end - start).total_seconds() * 1000)
            
            # 准备数据（新的字段结构）
            now_utc = TimeUtils.utc_now()
            data = {
                'request_id': request_id,
                'user_id': request_data['user_id'],  # 必须字段
                'conversation_id': request_data.get('conversation_id'),  # 可空
                'message_id': request_data.get('message_id'),  # 可空
                'session_context': request_data.get('session_context'),  # 新增字段
                'request_type': request_data.get('request_type', 'gemini_text'),
                'has_current_image': (False if request_data.get('has_current_image') is None else request_data.get('has_current_image')),
                'request_data': request_data.get('request_data', ''),  # 完整API请求JSON
                'image_data_info': request_data.get('image_data_info'),
                'raw_response': request_data.get('raw_response', ''),
                'response_meta': request_data.get('response_meta'),  # 最后chunk完整信息
                'model_name': cost_info['model_name'],
                'input_tokens': cost_info['total_input_tokens'],  # 使用新的字段名
                'output_tokens': cost_info['output_tokens'],
                'total_tokens': cost_info['total_tokens'],
                'input_cost_usd': cost_info['input_cost_usd'],
                'output_cost_usd': cost_info['output_cost_usd'],
                'total_cost_usd': cost_info['total_cost_usd'],
                'total_cost_cny': cost_info['total_cost_cny'],
                'request_start_time': request_data.get('request_start_time'),
                'first_token_time_ms': request_data.get('first_token_time_ms'),  # 耗时毫秒数
                'user_visible_time_ms': request_data.get('user_visible_time_ms'),  # 耗时毫秒数
                'completion_time': request_data.get('completion_time'),
                'total_duration_ms': duration_ms,
                'status': request_data.get('status', 'success'),
                'error_message': request_data.get('error_message'),
                'retry_count': request_data.get('retry_count', 0),
                # 添加缓存相关字段
                'used_cache': request_data.get('used_cache', False),
                'cache_name': request_data.get('cache_name'),
                'cached_tokens': request_data.get('cached_tokens'),
                'cache_cost_usd': request_data.get('cache_cost_usd'),
                'cache_cost_cny': request_data.get('cache_cost_cny'),
                'created_at': now_utc,
                'updated_at': now_utc
            }
            
            # 执行插入
            with self.engine.connect() as conn:
                insert_query = text("""
                    INSERT INTO api_requests (
                        request_id, user_id, conversation_id, message_id, session_context, request_type, has_current_image,
                        request_data, image_data_info,
                        raw_response, response_meta, model_name,
                        input_tokens, output_tokens, total_tokens,
                        input_cost_usd, output_cost_usd, total_cost_usd, total_cost_cny,
                        request_start_time, first_token_time_ms, user_visible_time_ms, completion_time, total_duration_ms,
                        status, error_message, retry_count,
                        used_cache, cache_name, cached_tokens, cache_cost_usd, cache_cost_cny,
                        created_at, updated_at
                    ) VALUES (
                        :request_id, :user_id, :conversation_id, :message_id, :session_context, :request_type, :has_current_image,
                        :request_data, :image_data_info,
                        :raw_response, :response_meta, :model_name,
                        :input_tokens, :output_tokens, :total_tokens,
                        :input_cost_usd, :output_cost_usd, :total_cost_usd, :total_cost_cny,
                        :request_start_time, :first_token_time_ms, :user_visible_time_ms, :completion_time, :total_duration_ms,
                        :status, :error_message, :retry_count,
                        :used_cache, :cache_name, :cached_tokens, :cache_cost_usd, :cache_cost_cny,
                        :created_at, :updated_at
                    )
                """)
                
                conn.execute(insert_query, data)
                conn.commit()
                
                logger.info(f"API请求记录已保存: {request_id}, 用户: {request_data['user_id']}, 上下文: {request_data.get('session_context', 'N/A')}, 成本: ${cost_info['total_cost_usd']} (¥{cost_info['total_cost_cny']})")
                return request_id
                
        except Exception as e:
            logger.error(f"保存API请求记录失败: {str(e)}")
            return None

    def update_api_request_log(self, request_id: str, updates: dict) -> bool:
        """根据 request_id 更新 api_requests 记录的部分字段，自动刷新 updated_at。"""
        try:
            if not request_id:
                return False

            # 可更新字段白名单
            allowed = {
                'user_id', 'conversation_id', 'message_id', 'session_context', 'request_type',
                'request_data', 'image_data_info', 'raw_response', 'response_meta', 'model_name',
                'input_tokens', 'output_tokens', 'total_tokens', 'input_cost_usd', 'output_cost_usd',
                'total_cost_usd', 'total_cost_cny', 'request_start_time', 'first_token_time_ms',
                'user_visible_time_ms', 'completion_time', 'total_duration_ms', 'status',
                'error_message', 'retry_count'
            }

            set_clauses = []
            params = {'request_id': request_id}
            for k, v in (updates or {}).items():
                if k in allowed:
                    set_clauses.append(f"{k} = :{k}")
                    params[k] = v

            if not set_clauses:
                return True

            set_clauses.append("updated_at = :updated_at")
            params['updated_at'] = TimeUtils.utc_now()

            query = text(f"""
                UPDATE api_requests
                SET {', '.join(set_clauses)}
                WHERE request_id = :request_id
            """)

            with self.engine.connect() as conn:
                conn.execute(query, params)
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"更新API请求日志失败: {str(e)}")
            return False

    # ============ 用户统计和缓存管理方法 ============
    
    def get_user_statistics(self, user_id):
        """获取用户统计信息 - PostgreSQL版本优化查询性能"""
        try:
            with self.engine.connect() as conn:
                # 优化版本：使用范围查询而非DATE()函数，可以利用索引
                result = conn.execute(
                    text("""
                        SELECT qm.subject, qm.complexity, qm.difficulty_level, COUNT(*) as count
                        FROM messages m
                        JOIN question_metadata qm ON m.metadata_id = qm.metadata_id
                        WHERE m.user_id = :user_id 
                          AND m.role = 'user' 
                          AND m.created_at >= CURRENT_DATE 
                          AND m.created_at < CURRENT_DATE + INTERVAL '1 day'
                        GROUP BY qm.subject, qm.complexity, qm.difficulty_level
                        ORDER BY count DESC
                    """),
                    {"user_id": user_id}
                )
                
                stats = []
                for row in result.fetchall():
                    stats.append({
                        'subject': row[0],
                        'complexity': row[1],
                        'difficulty_level': row[2],
                        'count': row[3]
                    })
                return stats
        except Exception as e:
            logger.error(f"获取问题统计失败: {str(e)}")
            return []

    def update_user_profile(self, user_id, profile_data):
        """更新用户画像 - 调用save_user_profile实现"""
        return self.save_user_profile(user_id, profile_data)

    def save_cache_status(self, cache_data):
        """保存缓存状态"""
        try:
            now_utc = TimeUtils.utc_now()
            
            with self.engine.connect() as conn:
                # 使用ON CONFLICT进行upsert操作（PostgreSQL特性）
                conn.execute(
                    text("""
                        INSERT INTO system_cache_status (
                            model_name, api_cache_name, system_instruction_hash, token_count,
                            expire_time, last_used, usage_count, cache_cost_usd, cache_cost_cny,
                            total_saved_usd, total_saved_cny, created_at, updated_at
                        ) VALUES (
                            :model_name, :api_cache_name, :system_instruction_hash, :token_count,
                            :expire_time, :last_used, :usage_count, :cache_cost_usd, :cache_cost_cny,
                            :total_saved_usd, :total_saved_cny, :created_at, :updated_at
                        )
                        ON CONFLICT (model_name) DO UPDATE SET
                            api_cache_name = EXCLUDED.api_cache_name,
                            system_instruction_hash = EXCLUDED.system_instruction_hash,
                            token_count = EXCLUDED.token_count,
                            expire_time = EXCLUDED.expire_time,
                            last_used = EXCLUDED.last_used,
                            usage_count = EXCLUDED.usage_count,
                            cache_cost_usd = EXCLUDED.cache_cost_usd,
                            cache_cost_cny = EXCLUDED.cache_cost_cny,
                            total_saved_usd = EXCLUDED.total_saved_usd,
                            total_saved_cny = EXCLUDED.total_saved_cny,
                            updated_at = EXCLUDED.updated_at
                    """),
                    {
                        "model_name": cache_data['model_name'],
                        "api_cache_name": cache_data['api_cache_name'],
                        "system_instruction_hash": cache_data.get('system_instruction_hash'),
                        "token_count": cache_data.get('token_count'),
                        "expire_time": cache_data.get('expire_time'),
                        "last_used": cache_data.get('last_used', now_utc),
                        "usage_count": cache_data.get('usage_count', 1),
                        "cache_cost_usd": float(cache_data.get('cache_cost_usd', 0.0)),
                        "cache_cost_cny": float(cache_data.get('cache_cost_cny', 0.0)),
                        "total_saved_usd": float(cache_data.get('total_saved_usd', 0.0)),
                        "total_saved_cny": float(cache_data.get('total_saved_cny', 0.0)),
                        "created_at": now_utc,
                        "updated_at": now_utc
                    }
                )
                
                conn.commit()
                logger.info(f"缓存状态已保存: {cache_data['model_name']}")
                return True
                
        except Exception as e:
            logger.error(f"保存缓存状态失败: {str(e)}")
            return False

    def cleanup_failed_welcome_messages(self, user_id):
        """清理指定用户失败的欢迎消息"""
        try:
            with self.engine.begin() as conn:
                # 找并删除失败的欢迎消息（round_num=-1且conversation_id为null的记录）
                result = conn.execute(
                    text("""
                        DELETE FROM messages 
                        WHERE user_id = :user_id 
                        AND round_num = -1 
                        AND conversation_id IS NULL
                        AND (
                            origin_content LIKE '%RetryError%' 
                            OR origin_content LIKE '%Error%'
                            OR origin_content LIKE '%Exception%'
                            OR origin_content IS NULL
                            OR origin_content = ''
                        )
                    """),
                    {"user_id": user_id}
                )
                deleted_count = result.rowcount
                if deleted_count > 0:
                    logger.info(f"已清理用户 {user_id} 的 {deleted_count} 条失败欢迎消息")
                return True
        except Exception as e:
            logger.error(f"清理失败欢迎消息时出错: {str(e)}")
            return False

    def save_user_profile(self, user_id, profile_content):
        """保存用户画像，设置为当前使用版本，之前版本设为非使用状态"""
        try:
            with self.engine.connect() as conn:
                # 将之前的画像设为非使用状态
                conn.execute(
                    text("UPDATE user_profiles SET in_use = FALSE WHERE user_id = :user_id"),
                    {"user_id": user_id}
                )
                # PostgreSQL使用RETURNING子句获取新插入的ID
                now = TimeUtils.utc_now()
                result = conn.execute(
                    text("""
                        INSERT INTO user_profiles (user_id, profile_content, in_use, created_at, updated_at)
                        VALUES (:user_id, :profile_content, TRUE, :created_at, :updated_at)
                        RETURNING profile_id
                    """),
                    {
                        "user_id": user_id, 
                        "profile_content": profile_content,
                        "created_at": now,
                        "updated_at": now
                    }
                )
                profile_id = result.fetchone()[0]
                conn.commit()
                return profile_id
        except Exception as e:
            logger.error(f"保存用户画像失败: {str(e)}")
            raise
    
    def get_active_user_profile(self, user_id):
        """获取用户当前使用的画像"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("SELECT profile_content FROM user_profiles WHERE user_id = :user_id AND in_use = TRUE ORDER BY created_at DESC LIMIT 1"),
                    {"user_id": user_id}
                )
                row = result.fetchone()
                return row[0] if row else None
        except Exception as e:
            logger.error(f"获取用户画像失败: {str(e)}")
            return None

    def get_conversation_messages_with_metadata(self, conversation_id):
        """获取对话消息及其元数据（支持新表结构）"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT m.message_id, m.role, m.origin_content, m.view_content, m.working_content, 
                               m.image_url, m.created_at, m.action_mode, m.is_valid_question, m.content_summary,
                               qm.subject, qm.complexity, qm.concepts, qm.question_type, qm.difficulty_level
                        FROM messages m
                        LEFT JOIN question_metadata qm ON m.metadata_id = qm.metadata_id
                        WHERE m.conversation_id = :conversation_id 
                        AND (m.send_status IS NULL OR m.send_status = 'success')
                        ORDER BY m.created_at ASC
                    """),
                    {"conversation_id": conversation_id}
                )
                
                messages = []
                for row in result.fetchall():
                    message_data = {
                        'message_id': row[0],
                        'role': row[1],
                        'origin_content': row[2],
                        'view_content': row[3],
                        'working_content': row[4],
                        'image_url': row[5],
                        'created_at': row[6],
                        'action_mode': row[7],
                        'is_valid_question': row[8],
                        'content_summary': row[9]
                    }
                    
                    # 添加元数据（如果存在）
                    if row[10]:  # subject不为空说明有元数据
                        message_data['metadata'] = {
                            'subject': row[10],
                            'complexity': row[11], 
                            'concepts': row[12],
                            'question_type': row[13],
                            'difficulty_level': row[14]
                        }
                    
                    messages.append(message_data)
                return messages
        except Exception as e:
            logger.error(f"获取对话消息及元数据失败: {str(e)}")
            return []

    def get_question_statistics(self, user_id, days=30):
        """获取用户问题统计 - PostgreSQL版本使用INTERVAL语法"""
        try:
            with self.engine.connect() as conn:
                # PostgreSQL版本：使用INTERVAL语法
                result = conn.execute(
                    text("""
                        SELECT qm.subject, qm.complexity, qm.difficulty_level, COUNT(*) as count
                        FROM messages m
                        JOIN question_metadata qm ON m.metadata_id = qm.metadata_id
                        WHERE m.user_id = :user_id 
                          AND m.role = 'user' 
                          AND m.created_at >= NOW() - INTERVAL '%s days'
                        GROUP BY qm.subject, qm.complexity, qm.difficulty_level
                        ORDER BY count DESC
                    """ % days),
                    {"user_id": user_id}
                )
                
                stats = []
                for row in result.fetchall():
                    stats.append({
                        'subject': row[0],
                        'complexity': row[1],
                        'difficulty_level': row[2],
                        'count': row[3]
                    })
                return stats
        except Exception as e:
            logger.error(f"获取问题统计失败: {str(e)}")
            return []

    def get_user_conversation_count(self, user_id):
        """获取用户对话数量"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("SELECT COUNT(*) FROM conversations WHERE user_id = :user_id AND is_deleted = FALSE"),
                    {"user_id": user_id}
                )
                return result.fetchone()[0]
        except Exception as e:
            logger.error(f"获取用户对话数量失败: {str(e)}")
            return 0

    def get_user_message_count(self, user_id):
        """获取用户消息数量"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("SELECT COUNT(*) FROM messages WHERE user_id = :user_id"),
                    {"user_id": user_id}
                )
                return result.fetchone()[0]
        except Exception as e:
            logger.error(f"获取用户消息数量失败: {str(e)}")
            return 0

    def get_user_last_message_time(self, user_id):
        """获取用户最后消息时间"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT created_at 
                        FROM messages 
                        WHERE user_id = :user_id 
                        ORDER BY created_at DESC 
                        LIMIT 1
                    """),
                    {"user_id": user_id}
                )
                row = result.fetchone()
                return row[0] if row else None
        except Exception as e:
            logger.error(f"获取用户最后消息时间失败: {str(e)}")
            return None

    def get_next_round_num(self, conversation_id):
        """获取下一个轮次号（排除server消息的轮次0）"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("SELECT MAX(round_num) FROM messages WHERE conversation_id = :conversation_id AND round_num > 0"),
                    {"conversation_id": conversation_id}
                )
                max_round = result.scalar()
                return (max_round or 0) + 1
        except Exception as e:
            logger.error(f"获取下一轮次号失败: {str(e)}")
            return 1

    def get_deleted_conversations(self, user_id, limit=50):
        """获取用户已删除的对话"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT conversation_id, title, deleted_at, created_at
                        FROM conversations 
                        WHERE user_id = :user_id AND is_deleted = TRUE
                        ORDER BY deleted_at DESC 
                        LIMIT :limit
                    """),
                    {"user_id": user_id, "limit": limit}
                )
                
                conversations = []
                for row in result.fetchall():
                    conversations.append({
                        'conversation_id': row[0],
                        'title': row[1],
                        'deleted_at': row[2],
                        'created_at': row[3]
                    })
                
                return conversations
                
        except Exception as e:
            logger.error(f"获取已删除对话失败: {str(e)}")
            return []

    # ============ 兼容性方法 ============
    # 提供与原DatabaseManager完全一致的接口
    
    def save_question_metadata(self, metadata_data):
        """保存问题元数据 - 兼容性方法"""
        try:
            now_utc = TimeUtils.utc_now()
            data = {
                "message_id": metadata_data['message_id'],
                "subject": metadata_data.get('subject'),
                "complexity": metadata_data.get('complexity'),
                "concepts": metadata_data.get('concepts'),
                "question_type": metadata_data.get('question_type'),
                "difficulty_level": metadata_data.get('difficulty_level'),
                "full_xml_content": metadata_data.get('full_xml_content'),
                "created_at": now_utc,
                "updated_at": now_utc
            }
            
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("""
                        INSERT INTO question_metadata 
                        (message_id, subject, complexity, concepts, question_type, difficulty_level, full_xml_content, created_at, updated_at)
                        VALUES (:message_id, :subject, :complexity, :concepts, :question_type, :difficulty_level, :full_xml_content, :created_at, :updated_at)
                        RETURNING metadata_id
                    """),
                    data
                )
                metadata_id = result.fetchone()[0]
                conn.commit()
                return metadata_id
                
        except Exception as e:
            logger.error(f"保存问题元数据失败: {str(e)}")
            return None

    def get_question_metadata(self, message_id):
        """获取问题元数据"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT metadata_id, subject, complexity, concepts, question_type, 
                               difficulty_level, full_xml_content, created_at
                        FROM question_metadata 
                        WHERE message_id = :message_id
                    """),
                    {"message_id": message_id}
                )
                row = result.fetchone()
                if row:
                    return {
                        'metadata_id': row[0],
                        'subject': row[1],
                        'complexity': row[2],
                        'concepts': row[3],
                        'question_type': row[4],
                        'difficulty_level': row[5],
                        'full_xml_content': row[6],
                        'created_at': row[7]
                    }
                return None
        except Exception as e:
            logger.error(f"获取问题元数据失败: {str(e)}")
            return None

    def get_subject_statistics(self, user_id):
        """获取学科统计 - 兼容性方法"""
        return self.get_question_statistics(user_id, days=30)

    # ============ 缓存管理扩展方法 ============
    
    def update_cache_usage(self, model_name, usage_increment=1):
        """更新缓存使用统计 - PostgreSQL版本使用NOW()"""
        try:
            with self.engine.connect() as conn:
                conn.execute(
                    text("""
                        UPDATE system_cache_status 
                        SET usage_count = usage_count + :usage_increment,
                            last_used = NOW(),
                            updated_at = NOW()
                        WHERE model_name = :model_name
                    """),
                    {"model_name": model_name, "usage_increment": usage_increment}
                )
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"更新缓存使用统计失败: {str(e)}")
            return False

    def cleanup_expired_cache(self):
        """清理过期缓存 - PostgreSQL版本使用NOW()"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("""
                        DELETE FROM system_cache_status 
                        WHERE expire_time < NOW()
                    """)
                )
                deleted_count = result.rowcount
                conn.commit()
                
                if deleted_count > 0:
                    logger.info(f"已清理 {deleted_count} 个过期缓存记录")
                return deleted_count
        except Exception as e:
            logger.error(f"清理过期缓存失败: {str(e)}")
            return 0

    def get_api_request_stats(self, user_id, days=7):
        """获取API请求统计 - 优化版：直接使用DECIMAL字段进行精确计算"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT COUNT(*) as request_count,
                               SUM(input_tokens) as total_input_tokens,
                               SUM(output_tokens) as total_output_tokens,
                               SUM(total_cost_usd) as total_cost_usd,
                               SUM(total_cost_cny) as total_cost_cny
                        FROM api_requests 
                        WHERE user_id = :user_id 
                          AND created_at >= NOW() - INTERVAL '%s days'
                          AND status = 'success'
                    """ % days),
                    {"user_id": user_id}
                )
                
                row = result.fetchone()
                if row:
                    return {
                        'request_count': row[0] or 0,
                        'total_input_tokens': row[1] or 0,
                        'total_output_tokens': row[2] or 0,
                        'total_cost_usd': str(row[3] or 0.0),
                        'total_cost_cny': str(row[4] or 0.0)
                    }
                return {
                    'request_count': 0,
                    'total_input_tokens': 0,
                    'total_output_tokens': 0,
                    'total_cost_usd': '0.0',
                    'total_cost_cny': '0.0'
                }
        except Exception as e:
            logger.error(f"获取API请求统计失败: {str(e)}")
            return {
                'request_count': 0,
                'total_input_tokens': 0,
                'total_output_tokens': 0,
                'total_cost_usd': '0.0',
                'total_cost_cny': '0.0'
            }

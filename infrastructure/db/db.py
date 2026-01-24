"""
数据库交互模块
封装所有与PostgreSQL数据库的直接交互操作
"""

import os
import logging
from sqlalchemy import create_engine, text, MetaData, Table, Column, Integer, String, Text, DateTime, Boolean
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime, timezone
from dotenv import load_dotenv
from tools.utils import TimeUtils
from infrastructure.db.db_time_standard import DatabaseTimeStandard

# 加载环境变量
load_dotenv()

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

Base = declarative_base()

class DatabaseManager:
    """数据库管理器（单例模式）"""
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DatabaseManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        """初始化数据库连接（只执行一次）"""
        if not self._initialized:
            self.engine = None
            self.connector = None
            self._init_connection()
            self._create_tables()
            DatabaseManager._initialized = True
    
    def _init_connection(self):
        """初始化数据库连接"""
        try:
            # 本地开发环境使用SQLite
            if os.getenv('LOCAL_DEV', 'false').lower() == 'true':
                self.db_type = 'sqlite'
                database_url = os.getenv('DATABASE_URL', 'sqlite:///data/sovi_demo.db')
                self.engine = create_engine(database_url, echo=False)
                logger.info(f"本地开发数据库连接初始化成功: {database_url}")
            else:
                # 生产环境使用PostgreSQL
                self.db_type = 'postgresql'
                
                # 检查是否使用Cloud SQL连接器
                use_cloud_sql = os.getenv('USE_CLOUD_SQL_CONNECTOR', 'false').lower() == 'true'
                
                if use_cloud_sql:
                    # 使用Cloud SQL连接器的Unix socket连接
                    instance_connection_name = os.getenv('INSTANCE_CONNECTION_NAME')
                    db_socket_dir = os.getenv('DB_SOCKET_DIR', '/cloudsql')
                    db_name = os.getenv('DB_NAME')
                    db_user = os.getenv('DB_USER')
                    db_password = os.getenv('DB_PASSWORD')
                    
                    # 使用psycopg2驱动，更好支持Cloud SQL连接器
                    database_url = f"postgresql+psycopg2://{db_user}:{db_password}@/{db_name}?host={db_socket_dir}/{instance_connection_name}"
                    logger.info(f"使用Cloud SQL连接器Unix socket连接: {db_socket_dir}/{instance_connection_name}")
                else:
                    # 使用传统TCP连接
                    db_host = os.getenv('DB_HOST')
                    db_port = os.getenv('DB_PORT', '5432')
                    db_name = os.getenv('DB_NAME')
                    db_user = os.getenv('DB_USER')
                    db_password = os.getenv('DB_PASSWORD')
                    database_url = f"postgresql+psycopg2://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
                    logger.info("使用传统TCP数据库连接")
                
                self.engine = create_engine(
                    database_url,
                    pool_size=3,          # 减少连接池大小
                    max_overflow=1,       # 减少溢出连接
                    pool_timeout=30,
                    pool_recycle=1800,
                    pool_pre_ping=True,   # 添加连接检测
                    echo=False
                )
                logger.info("PostgreSQL数据库连接初始化成功")
            
        except Exception as e:
            logger.error(f"数据库连接初始化失败: {str(e)}")
            raise
    
    def _create_tables(self):
        """创建数据库表（带存在性检查）"""
        try:
            # 检查主要表是否已存在
            if self._tables_exist():
                logger.info("数据库表已存在，跳过创建")
                return
                
            # 分步骤创建，避免PostgreSQL事务冲突
            self._create_base_tables()
            self._add_compatibility_columns()
            self._create_database_indexes()
            logger.info("数据库表和索引创建完成")
        except Exception as e:
            logger.error(f"创建数据库表失败: {str(e)}")
            raise

    def _tables_exist(self):
        """检查主要表是否已存在"""
        try:
            with self.engine.connect() as conn:
                # 检查核心表是否存在
                result = conn.execute(text("""
                    SELECT COUNT(*) FROM information_schema.tables 
                    WHERE table_name IN ('users', 'conversations', 'messages') 
                    AND table_schema = 'public'
                """))
                table_count = result.scalar()
                return table_count >= 3  # 至少存在3个核心表
        except Exception:
            return False

    def _create_base_tables(self):
        """第一步：创建基础表结构"""
        try:
            # 定义表结构
            metadata = MetaData()
            
            # users表 - 完整时间跟踪策略
            Table('users', metadata,
                Column('user_id', Integer, primary_key=True, autoincrement=True),
                Column('username', String(255), unique=True, nullable=False),
                Column('hashed_password', String(255), nullable=False),
                DatabaseTimeStandard.get_created_at_column(),
                DatabaseTimeStandard.get_updated_at_column(),
                extend_existing=True
            )
            
            # user_sessions表 - 完整时间跟踪策略
            Table('user_sessions', metadata,
                Column('session_id', String(36), primary_key=True),
                Column('user_id', Integer, nullable=False),
                Column('expires_at', DateTime, nullable=False),
                DatabaseTimeStandard.get_created_at_column(),
                DatabaseTimeStandard.get_updated_at_column(),
                extend_existing=True
            )
            
            # conversations表 - 扩展时间跟踪策略（包含删除时间）
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
            
            # messages表 - 完整时间跟踪策略（消息可能有编辑需求）
            Table('messages', metadata,
                Column('message_id', Integer, primary_key=True, autoincrement=True),
                Column('conversation_id', Integer, nullable=True),  # 改为可空，支持独立欢迎消息
                Column('user_id', Integer, nullable=False),  # 新增用户ID，支持独立消息查询
                Column('role', String(50), nullable=False),  # user/assistant/server
                Column('round_num', Integer, nullable=False, default=0),  # 轮次，-1=未激活欢迎消息，0=激活后第一轮
                Column('origin_content', Text, nullable=False),  # 用户原始输入
                Column('view_content', Text),  # 展示给用户的内容
                Column('working_content', Text),  # 处理后的工作内容
                Column('content_summary', Text),  # 内容摘要
                Column('action_mode', String(20)),  # 处理模式
                Column('is_valid_question', Boolean),  # 问题有效性
                Column('image_url', String(1024)),  # 图片URL
                Column('api_request_id', String(100)),  # 关联API请求记录ID(未来使用)
                Column('metadata_id', Integer),  # 关联question_metadata表ID
                Column('send_status', String(20), default='success'),  # 消息发送状态：pending/success/failed
                DatabaseTimeStandard.get_created_at_column(),
                DatabaseTimeStandard.get_updated_at_column(),
                extend_existing=True
            )

            # api_requests表 - 解耦版本，支持独立的API请求记录
            Table('api_requests', metadata,
                Column('id', Integer, primary_key=True, autoincrement=True),  # 自增主键
                Column('request_id', String(100), unique=True, nullable=False),  # UUID格式，唯一索引
                Column('user_id', Integer, nullable=False),  # 用户ID（新增）
                Column('conversation_id', Integer, nullable=True),  # 改为可空
                Column('message_id', Integer, nullable=True),  # 关联的消息ID，可空
                Column('session_context', String(200)),  # 会话上下文（如welcome_generation, normal_chat）
                Column('request_type', String(50)),  # gemini_text, gemini_vision
                Column('has_current_image', Boolean),  # 当前最新一条用户消息是否包含图片
                
                # 缓存相关字段
                Column('used_cache', Boolean, default=False),  # 是否使用了缓存
                Column('cache_name', String(255)),  # 使用的缓存名称
                Column('cached_tokens', Integer),  # 缓存的token数量
                Column('cache_cost_usd', String(20)),  # 缓存成本（美元）
                Column('cache_cost_cny', String(20)),  # 缓存成本（人民币）
                
                # 请求数据
                Column('request_data', Text),  # 完整的API请求JSON数据
                Column('image_data_info', Text),  # 图片信息（大小、格式等）
                
                # 响应数据
                Column('raw_response', Text),  # 模型原始完整响应
                Column('response_meta', Text),  # 最后一个chunk的完整信息（包含token统计）
                
                # Token和成本数据
                Column('model_name', String(50)),  # 使用的模型名称
                Column('input_tokens', Integer),
                Column('output_tokens', Integer), 
                Column('total_tokens', Integer),
                Column('input_cost_usd', String(20)),  # 输入成本（美元）
                Column('output_cost_usd', String(20)),  # 输出成本（美元）
                Column('total_cost_usd', String(20)),  # 总成本（美元）
                Column('total_cost_cny', String(20)),  # 总成本（人民币）
                
                # 时间和性能数据（改为耗时毫秒数，基于服务端接收用户消息开始计算）
                Column('request_start_time', DateTime),  # 保留请求开始时间点用于排序
                Column('first_token_time_ms', Integer),  # 首token耗时（毫秒）
                Column('user_visible_time_ms', Integer),  # 用户感知首token耗时（毫秒）
                Column('completion_time', DateTime),  # 保留完成时间点用于排序
                Column('total_duration_ms', Integer),
                
                # 错误和状态
                Column('status', String(20)),  # success, error, timeout
                Column('error_message', Text),
                Column('retry_count', Integer, default=0),
                
                # 标准时间字段
                DatabaseTimeStandard.get_created_at_column(),
                DatabaseTimeStandard.get_updated_at_column(),
                extend_existing=True
            )
            
            # system_cache_status表 - 系统缓存状态管理（简化设计）
            Table('system_cache_status', metadata,
                Column('id', Integer, primary_key=True, autoincrement=True),
                Column('model_name', String(100), unique=True, nullable=False),  # 模型名称作为唯一键
                Column('api_cache_name', String(255), nullable=False),  # Gemini API返回的真实缓存名称
                Column('system_instruction_hash', String(64)),  # 系统指令的哈希值，用于验证
                Column('token_count', Integer),  # 缓存的token数量
                Column('expire_time', DateTime),  # 过期时间
                Column('last_used', DateTime),  # 最后使用时间
                Column('usage_count', Integer, default=0),  # 使用次数
                Column('cache_cost_usd', String(20), default='0.000000'),  # 缓存成本（美元）
                Column('cache_cost_cny', String(20), default='0.0000'),  # 缓存成本（人民币）
                Column('total_saved_usd', String(20), default='0.000000'),  # 累计节省成本（美元）
                Column('total_saved_cny', String(20), default='0.0000'),  # 累计节省成本（人民币）
                DatabaseTimeStandard.get_created_at_column(),
                DatabaseTimeStandard.get_updated_at_column(),
                extend_existing=True
            )

            # question_metadata表 - 完整时间跟踪策略（元数据可能需要修正）
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
            
            # user_profiles表 - 完整时间跟踪策略（用户画像经常更新）
            Table('user_profiles', metadata,
                Column('profile_id', Integer, primary_key=True, autoincrement=True),
                Column('user_id', Integer, nullable=False),
                Column('profile_content', Text, nullable=False),  # Updated_User_Profile的完整markdown
                Column('in_use', Boolean, default=True, nullable=False),  # 是否为当前使用版本
                DatabaseTimeStandard.get_created_at_column(),
                DatabaseTimeStandard.get_updated_at_column(),
                extend_existing=True
            )
            
            # 创建表
            metadata.create_all(self.engine)
            logger.debug("基础数据库表创建成功")
            
        except Exception as e:
            logger.error(f"创建基础数据库表失败: {str(e)}")
            raise

    def _add_compatibility_columns(self):
        """第二步：兼容性字段检查（PostgreSQL部署无需额外操作）"""
        try:
            logger.debug("兼容性字段检查完成 - 全新PostgreSQL部署，所有字段已在表定义中包含")
            # 由于我们是全新部署到PostgreSQL，且表定义中已包含所有必要字段
            # 因此不需要执行ALTER TABLE操作
            
        except Exception as e:
            logger.warning(f"兼容性字段检查时出错: {e}")

    def _create_database_indexes(self):
        """第三步：创建数据库索引（独立事务）"""
        try:
            logger.debug("开始创建数据库索引")
            
            # 索引创建列表
            indexes = [
                ("idx_messages_conversation_round", "CREATE INDEX IF NOT EXISTS idx_messages_conversation_round ON messages(conversation_id, round_num)"),
                ("idx_messages_role", "CREATE INDEX IF NOT EXISTS idx_messages_role ON messages(role)"),
                ("idx_api_requests_status_time", "CREATE INDEX IF NOT EXISTS idx_api_requests_status_time ON api_requests(status, request_start_time)"),
                ("idx_api_requests_conversation", "CREATE INDEX IF NOT EXISTS idx_api_requests_conversation ON api_requests(conversation_id)"),
                ("idx_api_requests_message", "CREATE INDEX IF NOT EXISTS idx_api_requests_message ON api_requests(message_id)"),
                ("idx_question_metadata_message", "CREATE INDEX IF NOT EXISTS idx_question_metadata_message ON question_metadata(message_id)"),
                ("idx_question_metadata_subject", "CREATE INDEX IF NOT EXISTS idx_question_metadata_subject ON question_metadata(subject)")
            ]
            
            for index_name, sql in indexes:
                try:
                    with self.engine.connect() as conn:
                        conn.execute(text(sql))
                        conn.commit()
                        logger.debug(f"成功创建索引: {index_name}")
                except Exception as e:
                    logger.debug(f"索引 {index_name} 创建失败或已存在: {e}")
            
            logger.debug("数据库索引创建完成")
            
        except Exception as e:
            logger.warning(f"创建数据库索引时出错: {e}")

    def _cleanup_legacy_tables(self):
        """清理旧表结构（PostgreSQL兼容版本）"""
        try:
            # 这个方法暂时保留为空，因为我们是全新部署
            # 如果将来需要数据库迁移，在这里添加相关逻辑
            logger.info("旧表清理检查完成（跳过，全新部署）")
        except Exception as e:
            logger.warning(f"清理旧表时出错: {e}")
    
    # 用户相关操作
    def get_user_by_username(self, username):
        """根据用户名获取用户"""
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
            logger.error(f"获取用户失败: {str(e)}")
            return None
    
    def create_user(self, username, hashed_password):
        """创建新用户"""
        try:
            with self.engine.connect() as conn:
                # 准备用户数据（自动添加时间字段）
                user_data = {
                    "username": username, 
                    "hashed_password": hashed_password
                }
                user_data = DatabaseTimeStandard.prepare_create_data(user_data)
                
                # 插入用户
                conn.execute(
                    text("INSERT INTO users (username, hashed_password, created_at, updated_at) VALUES (:username, :hashed_password, :created_at, :updated_at)"),
                    user_data
                )
                conn.commit()
                
                # 再查询获取用户ID
                result = conn.execute(
                    text("SELECT user_id FROM users WHERE username = :username"),
                    {"username": username}
                )
                return result.fetchone()[0]
        except Exception as e:
            logger.error(f"创建用户失败: {str(e)}")
            raise
    
    # 会话相关操作
    def create_session(self, session_id, user_id, expires_at):
        """创建用户会话"""
        try:
            with self.engine.connect() as conn:
                # 准备会话数据（自动添加时间字段）
                session_data = {
                    "session_id": session_id, 
                    "user_id": user_id, 
                    "expires_at": expires_at
                }
                session_data = DatabaseTimeStandard.prepare_create_data(session_data)
                
                conn.execute(
                    text("INSERT INTO user_sessions (session_id, user_id, expires_at, created_at, updated_at) VALUES (:session_id, :user_id, :expires_at, :created_at, :updated_at)"),
                    session_data
                )
                conn.commit()
        except Exception as e:
            logger.error(f"创建会话失败: {str(e)}")
            raise
    
    def get_session(self, session_id):
        """获取会话信息"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("SELECT session_id, user_id, created_at, updated_at, expires_at FROM user_sessions WHERE session_id = :session_id"),
                    {"session_id": session_id}
                )
                row = result.fetchone()
                if row:
                    return {
                        'session_id': row[0],
                        'user_id': row[1],
                        'created_at': row[2],
                        'updated_at': row[3],
                        'expires_at': row[4]
                    }
                return None
        except Exception as e:
            logger.error(f"获取会话失败: {str(e)}")
            return None
    
    def get_valid_sessions(self):
        """获取所有有效的会话（未过期）"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT session_id, user_id, created_at, expires_at 
                        FROM user_sessions 
                        WHERE expires_at > :now 
                        ORDER BY created_at DESC
                    """),
                    {"now": TimeUtils.utc_now()}
                )
                rows = result.fetchall()
                return [
                    {
                        'session_id': row[0],
                        'user_id': row[1],
                        'created_at': row[2],
                        'expires_at': row[3]
                    }
                    for row in rows
                ]
        except Exception as e:
            logger.error(f"获取有效会话失败: {str(e)}")
            return []
    
    def get_user_by_id(self, user_id):
        """根据用户ID获取用户信息"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("SELECT user_id, username, hashed_password, created_at FROM users WHERE user_id = :user_id"),
                    {"user_id": user_id}
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
            logger.error(f"根据ID获取用户失败: {str(e)}")
            return None
    
    def delete_session(self, session_id):
        """删除会话"""
        try:
            with self.engine.connect() as conn:
                conn.execute(
                    text("DELETE FROM user_sessions WHERE session_id = :session_id"),
                    {"session_id": session_id}
                )
                conn.commit()
        except Exception as e:
            logger.error(f"删除会话失败: {str(e)}")
            raise
    
    def get_active_session_by_user_id(self, user_id):
        """根据用户ID获取有效的会话"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT session_id, user_id, created_at, expires_at 
                        FROM user_sessions 
                        WHERE user_id = :user_id AND expires_at > :now 
                        ORDER BY created_at DESC 
                        LIMIT 1
                    """),
                    {"user_id": user_id, "now": TimeUtils.utc_now()}
                )
                row = result.fetchone()
                if row:
                    return {
                        'session_id': row[0],
                        'user_id': row[1],
                        'created_at': row[2],
                        'expires_at': row[3]
                    }
                return None
        except Exception as e:
            logger.error(f"根据用户ID获取有效会话失败: {str(e)}")
            return None
    
    # 用户画像相关操作
    
    def update_user_profile(self, user_id, profile_data):
        """更新用户画像（兼容旧接口，内部统一走版本化写入 save_user_profile）。"""
        try:
            # 旧参数名 profile_data 与新列 profile_content 对齐
            self.save_user_profile(user_id, profile_data)
            return True
        except Exception as e:
            logger.error(f"更新用户画像失败: {str(e)}")
            raise
    
    # 对话相关操作
    def get_user_conversations(self, user_id, limit=50):
        """获取用户的对话列表（排除已删除）"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT conversation_id, title, created_at, updated_at 
                        FROM conversations 
                        WHERE user_id = :user_id AND is_deleted = false
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
            logger.error(f"获取对话列表失败: {str(e)}")
            return []
    
    def create_conversation(self, user_id, title):
        """创建新对话"""
        try:
            with self.engine.connect() as conn:
                with conn.begin():  # 使用显式事务
                    logger.info(f"开始创建对话: user_id={user_id}, title={title}")
                    
                    # 准备对话数据（自动添加时间字段）
                    conversation_data = {
                        "user_id": user_id, 
                        "title": title, 
                        "is_deleted": False
                    }
                    conversation_data = DatabaseTimeStandard.prepare_create_data(conversation_data)
                    
                    # 插入对话并获取ID
                    if self.db_type == 'postgresql':
                        result = conn.execute(
                            text("""
                                INSERT INTO conversations (user_id, title, is_deleted, created_at, updated_at)
                                VALUES (:user_id, :title, :is_deleted, :created_at, :updated_at)
                                RETURNING conversation_id
                            """),
                            conversation_data
                        )
                        conversation_id = result.fetchone()[0]
                        logger.info(f"PostgreSQL通过RETURNING获取到conversation_id: {conversation_id}")
                    else:
                        result = conn.execute(
                            text("""
                                INSERT INTO conversations (user_id, title, is_deleted, created_at, updated_at)
                                VALUES (:user_id, :title, :is_deleted, :created_at, :updated_at)
                            """),
                            conversation_data
                        )
                        
                        logger.info("对话插入成功，开始获取conversation_id")
                        
                        # SQLite获取ID方法
                        conversation_id = None
                        if hasattr(result, 'lastrowid') and result.lastrowid:
                            conversation_id = result.lastrowid
                            logger.info(f"通过result.lastrowid获取到conversation_id: {conversation_id}")
                        else:
                            # 备用方法：直接查询
                            id_result = conn.execute(text("SELECT last_insert_rowid()"))
                            conversation_id = id_result.fetchone()[0]
                            logger.info(f"通过SELECT last_insert_rowid()获取到conversation_id: {conversation_id}")
                    
                    if not conversation_id:
                        raise Exception("无法获取创建的conversation_id")
                    
                    # 验证对话是否真的创建成功
                    verify_result = conn.execute(
                        text("SELECT conversation_id, title FROM conversations WHERE conversation_id = :conv_id"),
                        {"conv_id": conversation_id}
                    )
                    verify_row = verify_result.fetchone()
                    if verify_row:
                        logger.info(f"对话创建验证成功: id={verify_row[0]}, title={verify_row[1]}")
                    else:
                        logger.error(f"对话创建验证失败: conversation_id={conversation_id} 不存在")
                        # 查询所有conversations表的内容
                        all_conversations = conn.execute(text("SELECT * FROM conversations")).fetchall()
                        logger.error(f"conversations表的所有记录: {all_conversations}")
                        raise Exception(f"对话创建失败：验证时无法找到conversation_id={conversation_id}")
                    
                    # 再次检查INSERT操作是否真的写入了数据
                    count_result = conn.execute(text("SELECT COUNT(*) FROM conversations WHERE conversation_id = :conv_id"), 
                                              {"conv_id": conversation_id})
                    count = count_result.fetchone()[0]
                    logger.info(f"conversations表中conversation_id={conversation_id}的记录数: {count}")
                    
                    if count != 1:
                        raise Exception(f"数据不一致:conversation_id={conversation_id}的记录数为{count}，应该为1")
                    
                    logger.info(f"对话创建完全成功,transaction即将提交: conversation_id={conversation_id}")
                    return conversation_id
                
        except Exception as e:
            logger.error(f"创建对话失败: {str(e)}")
            logger.error(f"错误详情: user_id={user_id}, title={title}")
            raise
    
    def get_conversation_messages(self, conversation_id):
        """获取对话消息（检查对话是否存在且未删除），包含发送失败的消息以支持重试功能"""
        try:
            with self.engine.connect() as conn:
                # 首先检查对话是否存在且未删除
                conv_check = conn.execute(
                    text("SELECT conversation_id FROM conversations WHERE conversation_id = :conv_id AND is_deleted = false"),
                    {"conv_id": conversation_id}
                )
                if not conv_check.fetchone():
                    logger.warning(f"对话 {conversation_id} 不存在或已被删除")
                    return []
                
                # 查询消息（包含发送失败的消息，因为前端需要显示重试按钮）
                result = conn.execute(
                    text("""
                        SELECT message_id, role, origin_content, view_content, working_content, 
                               image_url, send_status, created_at
                        FROM messages 
                        WHERE conversation_id = :conversation_id 
                        ORDER BY created_at ASC
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
                return messages
        except Exception as e:
            logger.error(f"获取对话消息失败: {str(e)}")
            return []

    def get_user_welcome_message(self, user_id, window_minutes=30):
        """获取用户最新的独立欢迎消息（round_num=-1），按整点和整半小时对齐的时间窗口"""
        try:
            with self.engine.connect() as conn:
                # 计算当前整点或整半小时对齐的时间窗口开始时间
                now_result = conn.execute(text("SELECT datetime('now')"))
                current_time_str = now_result.scalar()
                
                # 解析当前时间
                from datetime import datetime
                current_time = datetime.fromisoformat(current_time_str.replace(' ', 'T'))
                
                # 对齐到整点或整半小时
                aligned_minute = 0 if current_time.minute < 30 else 30
                aligned_time = current_time.replace(minute=aligned_minute, second=0, microsecond=0)
                
                # 格式化为SQLite可用的时间格式
                window_start = aligned_time.strftime('%Y-%m-%d %H:%M:%S')
                
                result = conn.execute(
                    text("""
                        SELECT message_id, origin_content, view_content, working_content, created_at
                        FROM messages 
                        WHERE user_id = :user_id 
                          AND role = 'server' 
                          AND round_num = -1 
                          AND datetime(created_at) >= datetime(:window_start)
                        ORDER BY created_at DESC 
                        LIMIT 1
                    """),
                    {"user_id": user_id, "window_start": window_start}
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
        """将独立欢迎消息转换为激活状态（设置conversation_id，round_num=0）"""
        try:
            with self.engine.connect() as conn:
                with conn.begin():
                    update_data = DatabaseTimeStandard.prepare_update_data({
                        "conversation_id": conversation_id,
                        "round_num": 0
                    })
                    update_data["message_id"] = message_id
                    
                    conn.execute(
                        text("""
                            UPDATE messages 
                            SET conversation_id = :conversation_id, 
                                round_num = :round_num, 
                                updated_at = :updated_at 
                            WHERE message_id = :message_id
                        """),
                        update_data
                    )
                    logger.info(f"欢迎消息已激活: message_id={message_id}, conversation_id={conversation_id}")
                    return True
        except Exception as e:
            logger.error(f"激活欢迎消息失败: {str(e)}")
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
    
    def save_message(self, conversation_id, role, origin_content, round_num=0, 
                     view_content=None, working_content=None, content_summary=None, 
                     action_mode=None, question_meta=None, is_valid_question=None, 
                     image_url=None, api_request_id=None, user_id=None, send_status='success'):
        """保存消息 (新版本 - 支持表拆分架构和独立欢迎消息)"""
        try:
            with self.engine.connect() as conn:
                with conn.begin():  # 使用显式事务
                    # 准备消息数据（自动添加时间字段）
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
                        "send_status": send_status
                    }
                    message_data = DatabaseTimeStandard.prepare_create_data(message_data)
                    
                    # 插入主消息记录并获取ID
                    if self.db_type == 'postgresql':
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
                    else:
                        # SQLite兼容版本
                        conn.execute(
                            text("""
                                INSERT INTO messages (conversation_id, user_id, role, round_num, origin_content, view_content, 
                                                    working_content, content_summary, action_mode, 
                                                    is_valid_question, image_url, api_request_id, send_status, created_at, updated_at)
                                VALUES (:conversation_id, :user_id, :role, :round_num, :origin_content, :view_content, 
                                       :working_content, :content_summary, :action_mode, 
                                       :is_valid_question, :image_url, :api_request_id, :send_status, :created_at, :updated_at)
                            """),
                            message_data
                        )
                        
                        # 获取插入的message_id
                        result = conn.execute(text("SELECT last_insert_rowid()"))
                        message_id = result.fetchone()[0]
                    
                    # 如果有question_meta数据，保存到独立表
                    metadata_id = None
                    if question_meta and role == 'assistant':
                        metadata_id = self._save_question_metadata(conn, message_id, question_meta)
                        
                        # 更新message记录中的metadata_id
                        conn.execute(
                            text("UPDATE messages SET metadata_id = :metadata_id WHERE message_id = :message_id"),
                            {"metadata_id": metadata_id, "message_id": message_id}
                        )
                    
                    # 更新会话更新时间（仅当有conversation_id时）
                    if conversation_id is not None:
                        update_data = DatabaseTimeStandard.prepare_update_data({"conversation_id": conversation_id})
                        update_result = conn.execute(
                            text("UPDATE conversations SET updated_at = :updated_at WHERE conversation_id = :conversation_id"),
                            update_data
                        )
                        
                        # 检查UPDATE是否影响了任何行
                        affected_rows = update_result.rowcount
                        logger.info(f"更新会话时间，影响行数: {affected_rows}")
                        
                        if affected_rows == 0:
                            # 如果没有影响任何行，说明conversation_id不存在
                            logger.error(f"严重错误: conversation_id={conversation_id} 在conversations表中不存在！")
                            # 查询一下conversations表的实际内容
                            check_result = conn.execute(text("SELECT conversation_id, title FROM conversations"))
                            existing_conversations = check_result.fetchall()
                            logger.error(f"当前conversations表内容: {existing_conversations}")
                            raise Exception(f"conversation_id={conversation_id} 不存在于conversations表中")
                    else:
                        logger.info(f"独立消息（无conversation_id），跳过会话更新: message_id={message_id}")
                    
                    logger.info(f"消息保存完成: message_id={message_id}, conversation_id={conversation_id}, user_id={user_id}")
                    return message_id
                
        except Exception as e:
            logger.error(f"保存消息失败: {str(e)}")
            raise

    def update_message_status(self, message_id: int, send_status: str) -> bool:
        """更新消息发送状态"""
        try:
            with self.engine.connect() as conn:
                update_data = DatabaseTimeStandard.prepare_update_data({
                    "send_status": send_status
                })
                update_data["message_id"] = message_id
                
                conn.execute(
                    text("UPDATE messages SET send_status = :send_status, updated_at = :updated_at WHERE message_id = :message_id"),
                    update_data
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

    def _save_question_metadata(self, conn, message_id, question_meta):
        """
        保存问题元数据到独立表。
        兼容两种输入：
        - XML字符串（推荐，用于完整保留）
        - dict（旧客户端解析结果），此时直接用字段入库，full_xml_content 存 JSON 文本。
        """
        try:
            import json
            # 标准化元数据字段
            if isinstance(question_meta, dict):
                metadata = {
                    'subject': question_meta.get('subject') or '',
                    'complexity': question_meta.get('complexity') or '',
                    'concepts': question_meta.get('concepts') or '',
                    'question_type': question_meta.get('question_type') or '',
                    'difficulty_level': question_meta.get('difficulty_level') or ''
                }
                full_text = json.dumps(question_meta, ensure_ascii=False)
            else:
                # 视为XML字符串，解析字段
                full_text = question_meta
                metadata = self._parse_question_meta_xml(question_meta)

            # 准备元数据（自动添加时间字段）
            metadata_with_time = {
                "message_id": message_id,
                "subject": metadata.get('subject'),
                "complexity": metadata.get('complexity'),
                "concepts": metadata.get('concepts'),
                "question_type": metadata.get('question_type'),
                "difficulty_level": metadata.get('difficulty_level'),
                "full_xml_content": full_text
            }
            metadata_with_time = DatabaseTimeStandard.prepare_create_data(metadata_with_time)

            # 插入元数据并获取ID
            if self.db_type == 'postgresql':
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
            else:
                conn.execute(
                    text("""
                        INSERT INTO question_metadata 
                        (message_id, subject, complexity, concepts, question_type, difficulty_level, full_xml_content, created_at, updated_at)
                        VALUES (:message_id, :subject, :complexity, :concepts, :question_type, :difficulty_level, :full_xml_content, :created_at, :updated_at)
                    """),
                    metadata_with_time
                )

                # SQLite获取插入的metadata_id
                result = conn.execute(text("SELECT last_insert_rowid()"))
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
                        SET is_deleted = true, deleted_at = :deleted_at, updated_at = :updated_at 
                        WHERE conversation_id = :conversation_id
                    """),
                    {
                        "conversation_id": conversation_id, 
                        "deleted_at": TimeUtils.utc_now(),
                        "updated_at": TimeUtils.utc_now()
                    }
                )
                conn.commit()
                logger.info(f"对话 {conversation_id} 已被用户 {user_id} 删除")
                return True
                
        except Exception as e:
            logger.error(f"删除对话失败: {str(e)}")
            return False
    
    def get_deleted_conversations(self, user_id, limit=50):
        """获取用户已删除的对话列表（用于恢复功能）"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT conversation_id, title, created_at, deleted_at 
                        FROM conversations 
                        WHERE user_id = :user_id AND is_deleted = true
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
                        'created_at': row[2],
                        'deleted_at': row[3]
                    })
                return conversations
        except Exception as e:
            logger.error(f"获取已删除对话列表失败: {str(e)}")
            return []
    
    def get_user_conversation_count(self, user_id):
        """获取用户对话总数"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("SELECT COUNT(*) FROM conversations WHERE user_id = :user_id AND (is_deleted = false OR is_deleted IS NULL)"),
                    {"user_id": user_id}
                )
                return result.scalar() or 0
        except Exception as e:
            logger.error(f"获取用户对话数量失败: {str(e)}")
            return 0
    
    def get_user_message_count(self, user_id):
        """获取用户发送的消息总数（不包括AI回复）"""
        try:
            with self.engine.connect() as conn:
                # 只统计用户发送的消息（role='user'）
                result = conn.execute(
                    text("""
                        SELECT COUNT(*) 
                        FROM messages m 
                        JOIN conversations c ON m.conversation_id = c.conversation_id 
                        WHERE c.user_id = :user_id 
                        AND m.role = 'user'
                        AND (c.is_deleted = false OR c.is_deleted IS NULL)
                    """),
                    {"user_id": user_id}
                )
                return result.scalar() or 0
        except Exception as e:
            logger.error(f"获取用户消息数量失败: {str(e)}")
            return 0
    
    def get_user_last_message_time(self, user_id):
        """获取用户最后一次发送消息的时间"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT m.created_at 
                        FROM messages m 
                        JOIN conversations c ON m.conversation_id = c.conversation_id 
                        WHERE c.user_id = :user_id 
                        AND m.role = 'user'
                        AND (c.is_deleted = false OR c.is_deleted IS NULL)
                        ORDER BY m.created_at DESC 
                        LIMIT 1
                    """),
                    {"user_id": user_id}
                )
                last_time = result.scalar()
                if last_time:
                    # 确保返回datetime对象
                    if isinstance(last_time, str):
                        # 如果是字符串，解析为datetime
                        from datetime import datetime
                        return datetime.fromisoformat(last_time.replace('Z', '+00:00'))
                    return last_time
                return None
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
    
    def save_user_profile(self, user_id, profile_content):
        """保存用户画像，设置为当前使用版本，之前版本设为非使用状态"""
        try:
            with self.engine.connect() as conn:
                # 将之前的画像设为非使用状态
                conn.execute(
                    text("UPDATE user_profiles SET in_use = false WHERE user_id = :user_id"),
                    {"user_id": user_id}
                )
                # 插入新的画像
                now = TimeUtils.utc_now()
                conn.execute(
                    text("""
                        INSERT INTO user_profiles (user_id, profile_content, in_use, created_at, updated_at)
                        VALUES (:user_id, :profile_content, true, :created_at, :updated_at)
                    """),
                    {
                        "user_id": user_id, 
                        "profile_content": profile_content,
                        "created_at": now,
                        "updated_at": now
                    }
                )
                conn.commit()
        except Exception as e:
            logger.error(f"保存用户画像失败: {str(e)}")
            raise
    
    def get_active_user_profile(self, user_id):
        """获取用户当前使用的画像"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("SELECT profile_content FROM user_profiles WHERE user_id = :user_id AND in_use = true ORDER BY created_at DESC LIMIT 1"),
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
        """获取用户问题统计（基于新元数据表）"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT qm.subject, qm.complexity, qm.difficulty_level, COUNT(*) as count
                        FROM question_metadata qm
                        JOIN messages m ON qm.message_id = m.message_id
                        JOIN conversations c ON m.conversation_id = c.conversation_id
                        WHERE c.user_id = :user_id 
                        AND qm.created_at > datetime('now', '-{} days')
                        GROUP BY qm.subject, qm.complexity, qm.difficulty_level
                        ORDER BY count DESC
                    """.format(days)),
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

    def save_api_request_log(self, request_data):
        """
        保存API请求日志（解耦版本）
        
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
                from datetime import datetime
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
            
            # 执行插入（更新字段列列表）
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

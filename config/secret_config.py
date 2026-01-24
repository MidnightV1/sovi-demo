"""
Google Secret Manager 配置管理模块

统一管理从Google Secret Manager获取敏感配置信息，
包括数据库密码、API密钥和服务账号JSON等。
"""

import os
import json
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class SecretManager:
    """Secret Manager客户端包装器"""
    
    def __init__(self):
        self.project_id = os.getenv('PROJECT_ID', 'sovi-demo')
        self._client = None
        
    @property
    def client(self):
        """延迟初始化Secret Manager客户端"""
        if self._client is None:
            try:
                from google.cloud import secretmanager
                self._client = secretmanager.SecretManagerServiceClient()
                logger.info("Secret Manager客户端初始化成功")
            except ImportError:
                logger.error("需要安装 google-cloud-secret-manager")
                raise
            except Exception as e:
                logger.error(f"Secret Manager客户端初始化失败: {e}")
                raise
        return self._client
    
    def get_secret(self, secret_name: str, version: str = "latest") -> Optional[str]:
        """从Secret Manager获取密钥
        
        Args:
            secret_name: 密钥名称
            version: 版本号，默认latest
            
        Returns:
            密钥值，失败返回None
        """
        try:
            name = f"projects/{self.project_id}/secrets/{secret_name}/versions/{version}"
            response = self.client.access_secret_version(request={"name": name})
            secret_value = response.payload.data.decode("UTF-8")
            logger.info(f"成功获取密钥: {secret_name}")
            return secret_value
        except Exception as e:
            logger.error(f"获取密钥失败 {secret_name}: {e}")
            return None
    
    def get_secret_json(self, secret_name: str, version: str = "latest") -> Optional[Dict[str, Any]]:
        """从Secret Manager获取JSON格式的密钥
        
        Args:
            secret_name: 密钥名称  
            version: 版本号，默认latest
            
        Returns:
            解析后的JSON字典，失败返回None
        """
        secret_value = self.get_secret(secret_name, version)
        if secret_value is None:
            return None
            
        try:
            return json.loads(secret_value)
        except json.JSONDecodeError as e:
            logger.error(f"解析JSON密钥失败 {secret_name}: {e}")
            return None


# 全局Secret Manager实例
_secret_manager = None


def get_secret_manager() -> SecretManager:
    """获取全局Secret Manager实例"""
    global _secret_manager
    if _secret_manager is None:
        _secret_manager = SecretManager()
    return _secret_manager


class CloudConfig:
    """Cloud环境配置管理"""
    
    def __init__(self):
        self.secret_manager = get_secret_manager()
        self._gemini_api_key = None
        self._database_password = None
        self._service_account_json = None
    
    @property
    def gemini_api_key(self) -> str:
        """获取Gemini API密钥"""
        if self._gemini_api_key is None:
            # 优先使用环境变量
            self._gemini_api_key = os.getenv('GEMINI_API_KEY')
            
            # 如果环境变量不存在，从Secret Manager获取
            if not self._gemini_api_key:
                self._gemini_api_key = self.secret_manager.get_secret('gemini-api-key')
                
            if not self._gemini_api_key:
                raise ValueError("无法获取Gemini API密钥")
                
        return self._gemini_api_key
    
    @property  
    def database_password(self) -> str:
        """获取数据库密码"""
        if self._database_password is None:
            # 优先使用环境变量
            self._database_password = os.getenv('DB_PASSWORD')
            
            # 如果环境变量不存在，从Secret Manager获取
            if not self._database_password:
                self._database_password = self.secret_manager.get_secret('sovi-db-password')
                
            if not self._database_password:
                raise ValueError("无法获取数据库密码")
                
        return self._database_password
    
    @property
    def service_account_json(self) -> Optional[Dict[str, Any]]:
        """获取服务账号JSON"""
        if self._service_account_json is None:
            # 优先检查环境变量中的文件路径
            creds_path = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
            if creds_path and os.path.exists(creds_path):
                try:
                    with open(creds_path, 'r') as f:
                        self._service_account_json = json.load(f)
                    return self._service_account_json
                except Exception as e:
                    logger.warning(f"读取服务账号文件失败: {e}")
            
            # 从Secret Manager获取
            self._service_account_json = self.secret_manager.get_secret_json('gcs-key')
            
        return self._service_account_json
    
    def get_database_url(self) -> str:
        """构建数据库连接URL"""
        # 如果已设置完整URL，直接使用
        database_url = os.getenv('DATABASE_URL')
        if database_url:
            return database_url
            
        # 检查是否使用Cloud SQL连接器
        use_cloud_sql_connector = os.getenv('USE_CLOUD_SQL_CONNECTOR', 'false').lower() == 'true'
        
        if use_cloud_sql_connector:
            # 使用Unix socket连接 (Cloud SQL连接器)
            instance_name = os.getenv('INSTANCE_CONNECTION_NAME')
            if not instance_name:
                raise ValueError("INSTANCE_CONNECTION_NAME environment variable is required for Cloud SQL connector")
            socket_path = f"/cloudsql/{instance_name}"
            name = os.getenv('DB_NAME', 'sovi_data')
            user = os.getenv('DB_USER')
            if not user:
                raise ValueError("DB_USER environment variable is required")
            password = self.database_password
            return f"postgresql+pg8000://{user}:{password}@/{name}?unix_sock={socket_path}/.s.PGSQL.5432"
        else:
            # 使用TCP连接 (直接IP连接)
            host = os.getenv('DB_HOST')
            if not host:
                raise ValueError("DB_HOST environment variable is required for TCP connection")
            port = os.getenv('DB_PORT', '5432')
            name = os.getenv('DB_NAME', 'sovi_data')
            user = os.getenv('DB_USER')
            if not user:
                raise ValueError("DB_USER environment variable is required")
            password = self.database_password
            return f"postgresql+pg8000://{user}:{password}@{host}:{port}/{name}"


# 全局Cloud配置实例
_cloud_config = None


def get_cloud_config() -> CloudConfig:
    """获取全局Cloud配置实例"""
    global _cloud_config
    if _cloud_config is None:
        _cloud_config = CloudConfig()
    return _cloud_config

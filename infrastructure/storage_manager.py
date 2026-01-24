#!/usr/bin/env python3
"""
图片存储管理器
提供统一的存储接口，支持本地存储和GCS存储
"""

import os
import uuid
import base64
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple, BinaryIO
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

class ImageStorageManager(ABC):
    """
    图片存储管理器抽象基类
    """
    
    @abstractmethod
    def upload_image(self, image_data: bytes, user_id: str, file_extension: str = "jpg") -> Optional[Tuple[str, str]]:
        """
        上传图片
        
        Args:
            image_data: 图片二进制数据
            user_id: 用户ID
            file_extension: 文件扩展名
            
        Returns:
            (storage_path, access_url) 或 None（如果失败）
        """
        pass
    
    @abstractmethod
    def get_image_url(self, storage_path: str) -> str:
        """
        获取图片访问URL
        
        Args:
            storage_path: 存储路径
            
        Returns:
            访问URL
        """
        pass
    
    @abstractmethod
    def get_image_data(self, storage_path: str) -> Optional[bytes]:
        """
        获取图片数据
        
        Args:
            storage_path: 存储路径或URL
            
        Returns:
            图片二进制数据
        """
        pass
    
    @abstractmethod
    def delete_image(self, storage_path: str) -> bool:
        """
        删除图片
        
        Args:
            storage_path: 存储路径
            
        Returns:
            是否删除成功
        """
        pass


class LocalImageStorage(ImageStorageManager):
    """
    本地图片存储管理器
    """
    
    def __init__(self, storage_dir: str = "temp_image_storage"):
        """
        初始化本地存储
        
        Args:
            storage_dir: 存储目录
        """
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(exist_ok=True)
    
    def _generate_filename(self, user_id: str, file_extension: str) -> str:
        """生成文件名 - 使用UUID，不暴露用户信息"""
        file_id = str(uuid.uuid4())
        return f"{file_id}.{file_extension}"
    
    def _get_date_path(self) -> str:
        """获取基于UTC时间的日期路径"""
        utc_now = datetime.now(timezone.utc)
        return utc_now.strftime("%Y/%m/%d")
    
    def upload_image(self, image_data: bytes, user_id: str, file_extension: str = "jpg") -> Optional[Tuple[str, str]]:
        """上传图片到本地存储"""
        try:
            filename = self._generate_filename(user_id, file_extension)
            date_path = self._get_date_path()
            
            # 创建日期目录
            date_dir = self.storage_dir / date_path.replace("/", os.sep)
            date_dir.mkdir(parents=True, exist_ok=True)
            
            # 完整文件路径
            file_path = date_dir / filename
            
            # 写入文件
            with open(file_path, 'wb') as f:
                f.write(image_data)
            
            # 返回相对路径（包含日期）和访问URL
            relative_path = f"{date_path}/{filename}"
            access_url = f"/temp_image_storage/{relative_path}"
            
            print(f"[OK] 本地图片上传成功: {file_path}")
            return relative_path, access_url
            
        except Exception as e:
            print(f"[ERROR] 本地图片上传失败: {e}")
            return None
    
    def get_image_url(self, storage_path: str) -> str:
        """获取本地图片的访问URL"""
        if storage_path.startswith("/temp_image_storage/"):
            return storage_path
        
        # 如果是相对路径（包含日期），转换为URL
        if not storage_path.startswith("/"):
            return f"/temp_image_storage/{storage_path}"
        
        return storage_path
    
    def get_image_data(self, storage_path: str) -> Optional[bytes]:
        """获取本地图片数据"""
        try:
            # 处理URL格式：/temp_image_storage/2025/08/16/uuid.jpg
            if storage_path.startswith("/temp_image_storage/"):
                relative_path = storage_path[len("/temp_image_storage/"):]
                file_path = self.storage_dir / relative_path.replace("/", os.sep)
            elif not storage_path.startswith("/"):
                # 直接是相对路径：2025/08/16/uuid.jpg
                file_path = self.storage_dir / storage_path.replace("/", os.sep)
            else:
                file_path = Path(storage_path)
            
            if file_path.exists():
                with open(file_path, 'rb') as f:
                    return f.read()
            else:
                print(f"[ERROR] 文件不存在: {file_path}")
                return None
                
        except Exception as e:
            print(f"[ERROR] 读取本地图片失败: {e}")
            return None
    
    def delete_image(self, storage_path: str) -> bool:
        """删除本地图片"""
        try:
            if storage_path.startswith("/temp_image_storage/"):
                relative_path = storage_path[len("/temp_image_storage/"):]
                file_path = self.storage_dir / relative_path.replace("/", os.sep)
            elif not storage_path.startswith("/"):
                # 直接是相对路径
                file_path = self.storage_dir / storage_path.replace("/", os.sep)
            else:
                file_path = Path(storage_path)
            
            if file_path.exists():
                file_path.unlink()
                print(f"[OK] 本地图片删除成功: {file_path}")
                return True
            else:
                print(f"[WARN] 文件不存在: {file_path}")
                return False
                
        except Exception as e:
            print(f"[ERROR] 删除本地图片失败: {e}")
            return False


class GCSImageStorage(ImageStorageManager):
    """Google Cloud Storage图片存储管理器"""
    
    def __init__(self, project_id: str, bucket_name: str):
        """
        初始化GCS存储
        
        Args:
            project_id: GCP项目ID
            bucket_name: 存储桶名称
        """
        self.project_id = project_id
        self.bucket_name = bucket_name
        
        try:
            from google.cloud import storage
            
            # 检查是否提供了服务账号JSON环境变量
            service_account_json = os.getenv('GCS_SERVICE_ACCOUNT_JSON')
            
            if service_account_json:
                # 使用环境变量中的服务账号JSON
                import json
                from google.oauth2 import service_account
                service_account_info = json.loads(service_account_json)
                credentials = service_account.Credentials.from_service_account_info(service_account_info)
                self.client = storage.Client(project=project_id, credentials=credentials)
                print(f"[OK] 使用环境变量服务账号初始化GCS")
            else:
                # 在Cloud Run环境中使用默认服务账号
                self.client = storage.Client(project=project_id)
                print(f"[OK] 使用默认服务账号初始化GCS")
                
            self.bucket = self.client.bucket(bucket_name)
            self._ensure_bucket_exists()
            print(f"[OK] GCS存储初始化成功: {bucket_name}")
        except ImportError:
            raise ImportError("需要安装 google-cloud-storage: pip install google-cloud-storage")
        except Exception as e:
            print(f"[ERROR] GCS初始化失败: {e}")
            raise
    
    def _ensure_bucket_exists(self):
        """确保存储桶存在"""
        try:
            if not self.bucket.exists():
                print(f"[GCS] Creating bucket: {self.bucket_name}")
                bucket = self.client.create_bucket(self.bucket_name, location="US")
                bucket.make_public()
                print(f"[OK] GCS存储桶创建成功")
            else:
                print(f"[OK] GCS存储桶已存在: {self.bucket_name}")
        except Exception as e:
            print(f"[WARN] GCS存储桶检查失败: {e}")
    
    def _generate_object_name(self, user_id: str, file_extension: str) -> str:
        """生成GCS对象名称 - 基于UTC时间分层，文件名不暴露用户信息"""
        utc_now = datetime.now(timezone.utc)
        date_path = utc_now.strftime("%Y/%m/%d")
        file_id = str(uuid.uuid4())
        return f"uploads/{date_path}/{file_id}.{file_extension}"
    
    def upload_image(self, image_data: bytes, user_id: str, file_extension: str = "jpg") -> Optional[Tuple[str, str]]:
        """上传图片到GCS"""
        try:
            from google.cloud.exceptions import GoogleCloudError
            
            object_name = self._generate_object_name(user_id, file_extension)
            blob = self.bucket.blob(object_name)
            
            # 设置内容类型
            content_type = f"image/{file_extension}"
            blob.content_type = content_type
            
            # 上传数据
            blob.upload_from_string(image_data, content_type=content_type)
            blob.make_public()
            
            # 生成公共URL
            access_url = self.get_image_url(object_name)
            
            print(f"[OK] GCS图片上传成功: {object_name}")
            return object_name, access_url
            
        except Exception as e:
            print(f"[ERROR] GCS图片上传失败: {e}")
            return None
    
    def get_image_url(self, storage_path: str) -> str:
        """获取GCS图片的公共URL"""
        if storage_path.startswith("https://"):
            return storage_path
        return f"https://storage.googleapis.com/{self.bucket_name}/{storage_path}"
    
    def get_image_data(self, storage_path: str) -> Optional[bytes]:
        """获取GCS图片数据"""
        try:
            from google.cloud.exceptions import GoogleCloudError
            
            # 处理URL格式
            if storage_path.startswith("https://storage.googleapis.com/"):
                # 从URL提取对象名称
                url_parts = storage_path.split("/")
                bucket_index = url_parts.index(self.bucket_name)
                object_name = "/".join(url_parts[bucket_index + 1:])
            else:
                object_name = storage_path
            
            blob = self.bucket.blob(object_name)
            return blob.download_as_bytes()
            
        except Exception as e:
            print(f"[ERROR] 获取GCS图片数据失败: {e}")
            return None
    
    def delete_image(self, storage_path: str) -> bool:
        """删除GCS图片"""
        try:
            from google.cloud.exceptions import GoogleCloudError
            
            # 处理URL格式
            if storage_path.startswith("https://storage.googleapis.com/"):
                url_parts = storage_path.split("/")
                bucket_index = url_parts.index(self.bucket_name)
                object_name = "/".join(url_parts[bucket_index + 1:])
            else:
                object_name = storage_path
            
            blob = self.bucket.blob(object_name)
            blob.delete()
            print(f"[OK] GCS图片删除成功: {object_name}")
            return True
            
        except Exception as e:
            print(f"[ERROR] GCS图片删除失败: {e}")
            return False


# 全局存储管理器实例缓存
_storage_manager_instance = None

def get_storage_manager() -> ImageStorageManager:
    """
    获取存储管理器实例（单例模式）
    根据配置返回本地存储或GCS存储
    """
    global _storage_manager_instance
    
    # 如果已有实例，直接返回
    if _storage_manager_instance is not None:
        return _storage_manager_instance
    
    from config import Config
    
    if Config.USE_GCS_STORAGE:
        try:
            project_id = os.getenv('GCP_PROJECT_ID')
            bucket_name = Config.GCS_BUCKET_NAME
            
            if not project_id:
                raise ValueError("使用GCS存储需要设置 GCP_PROJECT_ID")
            
            if not bucket_name:
                raise ValueError("使用GCS存储需要设置 GCS_BUCKET_NAME")
            
            print(f"[GCS] 使用GCS存储: {bucket_name} (项目: {project_id})")
            storage_instance = GCSImageStorage(project_id, bucket_name)
            
            # 验证存储管理器是否正常工作
            test_url = storage_instance.get_image_url("uploads/test/verification.jpg")
            print(f"[GCS] URL test: uploads/test/verification.jpg -> {test_url}")
            
            # 缓存实例
            _storage_manager_instance = storage_instance
            return storage_instance
            
        except Exception as e:
            print(f"[ERROR] GCS存储初始化失败，回退到本地存储: {e}")
            print(f"[ENV] Check:")
            print(f"  - GCP_PROJECT_ID: {os.getenv('GCP_PROJECT_ID')}")
            print(f"  - GCS_BUCKET_NAME: {Config.GCS_BUCKET_NAME}")
            print(f"  - USE_GCS_STORAGE: {Config.USE_GCS_STORAGE}")
            storage_instance = LocalImageStorage(Config.LOCAL_STORAGE_PATH)
            _storage_manager_instance = storage_instance
            return storage_instance
    else:
        print(f"[LOCAL] Using local storage: {Config.LOCAL_STORAGE_PATH}")
        storage_instance = LocalImageStorage(Config.LOCAL_STORAGE_PATH)
        _storage_manager_instance = storage_instance
        return storage_instance


# 测试功能
def test_storage_manager():
    """测试存储管理器"""
    print("=" * 60)
    print("[TEST] Storage manager test")
    print("=" * 60)
    
    # 获取存储管理器
    storage = get_storage_manager()
    print(f"存储类型: {type(storage).__name__}")
    
    # 显示URL格式示例
    if isinstance(storage, GCSImageStorage):
        # GCS URL示例
        demo_object = storage._generate_object_name("test_user", "jpg")
        demo_url = storage.get_image_url(demo_object)
        print(f"\n[GCS] URL format:")
        print(f"  对象路径: {demo_object}")
        print(f"  公众URL: {demo_url}")
    else:
        # 本地存储URL示例
        demo_path = storage._get_date_path() + "/" + storage._generate_filename("test_user", "jpg")
        demo_url = storage.get_image_url(demo_path)
        print(f"\n[LOCAL] Storage URL format:")
        print(f"  存储路径: {demo_path}")
        print(f"  访问URL: {demo_url}")
    
    # 创建测试图片数据
    test_image = b"fake_image_data_for_testing"
    
    # 测试上传
    result = storage.upload_image(test_image, "test_user", "jpg")
    if result:
        storage_path, access_url = result
        print(f"\n[OK] 上传测试成功:")
        print(f"  存储路径: {storage_path}")
        print(f"  访问URL: {access_url}")
        
        # 测试获取URL
        url = storage.get_image_url(storage_path)
        print(f"  生成URL: {url}")
        
        # 测试删除
        deleted = storage.delete_image(storage_path)
        print(f"  删除结果: {'成功' if deleted else '失败'}")
    else:
        print("[ERROR] 上传测试失败")


if __name__ == '__main__':
    test_storage_manager()

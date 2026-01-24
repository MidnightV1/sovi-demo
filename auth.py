"""
Flask用户认证模块
处理用户注册、登录、密码验证和会话管理
"""

import bcrypt
import re
import uuid
from config import Config
from tools.utils import TimeUtils

class AuthManager:
    """Flask用户认证管理器"""
    
    def __init__(self):
        """初始化认证管理器"""
        self.db_manager = Config.get_database_manager()
    
    def _generate_session_token(self, user_id):
        """为用户生成会话令牌"""
        try:
            # 生成唯一的会话ID
            session_id = str(uuid.uuid4())
            
            # 计算过期时间（7天后）
            expires_at = TimeUtils.get_session_expiry(days=7)
            
            # 创建会话记录
            self.db_manager.create_session(session_id, user_id, expires_at)
            
            return session_id
        except Exception as e:
            print(f"生成会话令牌失败: {str(e)}")
            return None
    
    def _restore_session_from_token(self, token):
        """从令牌恢复会话"""
        if not token:
            return None
        
        try:
            # 获取会话信息
            session = self.db_manager.get_session(token)
            if not session:
                return None
            
            # 检查会话是否过期
            if TimeUtils.is_expired(session.get('expires_at')):
                # 删除过期的会话
                self.db_manager.delete_session(token)
                return None
            
            # 获取用户信息
            user = self.db_manager.get_user_by_id(session['user_id'])
            return user
        except Exception as e:
            print(f"会话恢复失败: {str(e)}")
            return None
    
    def login_or_register_flask(self, username, password):
        """统一的登录/注册方法（Flask版本）"""
        try:
            # 验证输入
            if not self._validate_username(username):
                return None, "用户名格式不正确：只能包含字母、数字和下划线，长度3-20字符"
            
            if not self._validate_password(password):
                return None, "密码格式不正确：至少6个字符"
            
            # 尝试获取现有用户
            existing_user = self.db_manager.get_user_by_username(username)
            
            if existing_user:
                # 用户存在，尝试登录
                if self._verify_password(password, existing_user['hashed_password']):
                    return existing_user, "登录成功"
                else:
                    return None, "密码错误"
            else:
                # 用户不存在，自动注册
                user_id = self._register_user(username, password)
                if user_id:
                    new_user = self.db_manager.get_user_by_id(user_id)
                    if new_user:
                        return new_user, "欢迎加入Sovi！账户已自动创建"
                    else:
                        return None, "注册后获取用户信息失败"
                else:
                    return None, "注册失败，请重试"
                    
        except Exception as e:
            return None, f"认证过程出错: {str(e)}"
    
    def _validate_username(self, username):
        """验证用户名格式"""
        if not username or len(username) < 3 or len(username) > 20:
            return False
        return re.match(r'^[a-zA-Z0-9_]+$', username) is not None
    
    def _validate_password(self, password):
        """验证密码长度（Demo用弱校验）"""
        return password and len(password) >= 6
    
    def _hash_password(self, password):
        """哈希密码"""
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')
    
    def _verify_password(self, password, hashed_password):
        """验证密码"""
        try:
            return bcrypt.checkpw(password.encode('utf-8'), hashed_password.encode('utf-8'))
        except Exception as e:
            print(f"密码验证错误: {str(e)}")
            return False
    
    def _register_user(self, username, password):
        """注册新用户"""
        try:
            hashed_password = self._hash_password(password)
            user_id = self.db_manager.create_user(username, hashed_password)
            return user_id
        except Exception as e:
            print(f"用户注册失败: {str(e)}")
            return None
    
    def logout_user(self, session_token):
        """用户登出"""
        if session_token:
            try:
                self.db_manager.delete_session(session_token)
                return True
            except Exception as e:
                print(f"登出失败: {str(e)}")
        return False

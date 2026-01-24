"""
工具函数模块（已迁移至 tools.utils）
提供时间处理、格式化等通用功能
"""

from datetime import datetime, timezone


class TimeUtils:
    """时间处理工具类"""

    @staticmethod
    def utc_now():
        """获取当前UTC时间"""
        return datetime.now(timezone.utc)

    @staticmethod
    def to_utc(dt):
        """将本地时间转换为UTC时间"""
        if dt is None:
            return None

        if dt.tzinfo is None:
            # 如果没有时区信息，假设为本地时间
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(timezone.utc)

    @staticmethod
    def format_iso_utc(dt):
        """将datetime对象格式化为ISO格式的UTC时间字符串"""
        if dt is None:
            return None

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        # 确保转换为UTC
        utc_dt = dt.astimezone(timezone.utc)
        # 返回ISO格式，包含Z后缀表示UTC
        return utc_dt.isoformat().replace('+00:00', 'Z')

    @staticmethod
    def parse_iso_utc(iso_string):
        """解析ISO格式的UTC时间字符串为datetime对象"""
        if not iso_string:
            return None

        # 处理Z后缀
        if iso_string.endswith('Z'):
            iso_string = iso_string[:-1] + '+00:00'

        try:
            return datetime.fromisoformat(iso_string)
        except ValueError:
            # 如果解析失败，尝试其他格式
            try:
                return datetime.strptime(iso_string, '%Y-%m-%dT%H:%M:%S.%f')
            except ValueError:
                return datetime.strptime(iso_string, '%Y-%m-%dT%H:%M:%S')

    @staticmethod
    def get_session_expiry(days=7):
        """获取会话过期时间（UTC）"""
        from datetime import timedelta
        return TimeUtils.utc_now() + timedelta(days=days)

    @staticmethod
    def is_expired(expires_at):
        """检查时间是否已过期"""
        if expires_at is None:
            return True

        if isinstance(expires_at, str):
            expires_at = TimeUtils.parse_iso_utc(expires_at)

        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        return expires_at < TimeUtils.utc_now()

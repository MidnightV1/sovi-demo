from __future__ import annotations

class ApiClientError(Exception):
    """通用API客户端错误。"""
    pass

class ApiTimeoutError(ApiClientError):
    pass

class ApiRateLimitError(ApiClientError):
    pass

class ApiConfigError(ApiClientError):
    """配置或环境错误，例如缺少API Key或未初始化传输层。"""
    pass

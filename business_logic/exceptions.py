from __future__ import annotations


class BusinessLogicError(Exception):
    """业务逻辑层基础异常"""
    pass


class XmlParseError(BusinessLogicError):
    """XML解析失败异常"""
    def __init__(self, raw_response: str, parse_error: str):
        self.raw_response = raw_response
        self.parse_error = parse_error
        super().__init__(f"XML解析失败: {parse_error}")


class DatabaseTransactionError(BusinessLogicError):
    """数据库事务异常"""
    pass

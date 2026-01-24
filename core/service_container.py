from __future__ import annotations
from typing import Any, Callable, Dict
from config import Config
from business_logic.transaction_manager import TransactionManager
from business_logic.message_status_service import MessageStatusService
from business_logic.session_meta_service import SessionMetaService
from business_logic.profile_service import ProfileService
from business_logic.response_parser import ResponseParser
from business_logic.chat_orchestrator import ChatOrchestrator
from business_logic.welcome_service import WelcomeService


class ServiceContainer:
    """极简的依赖注入容器（阶段1）。"""

    def __init__(self) -> None:
        self._singletons: Dict[str, Any] = {}
        self._factories: Dict[str, Callable[[], Any]] = {}
        self._instances: Dict[str, Any] = {}

    def register_singleton(self, name: str, instance: Any) -> None:
        self._singletons[name] = instance

    def register_factory(self, name: str, factory: Callable[[], Any]) -> None:
        self._factories[name] = factory

    def get(self, name: str) -> Any:
        if name in self._instances:
            return self._instances[name]
        if name in self._singletons:
            return self._singletons[name]
        if name in self._factories:
            instance = self._factories[name]()
            self._instances[name] = instance
            return instance
        raise ValueError(f"服务 '{name}' 未注册")

    @classmethod
    def build_default(cls) -> "ServiceContainer":
        """构建默认容器，注册核心服务。"""
        c = cls()
        # db
        db = Config.get_database_manager()
        c.register_singleton('db', db)
        # 底层传输层：单例复用
        from api_clients.google_transport import GoogleTransport
        transport_singleton = GoogleTransport()
        c.register_singleton('transport', transport_singleton)

        # 新架构的gemini客户端（直接使用新客户端），复用传输层单例
        def _make_new_gemini():
            from api_clients.gemini_client import GeminiClient
            from config import Config
            transport = c.get('transport')
            return GeminiClient(transport=transport, model_name=Config.GEMINI_MODEL)

        c.register_factory('gemini_client', _make_new_gemini)

        # 系统缓存管理器（仅用于系统prompt缓存），复用传输层以访问底层 .client
        def _make_cache_mgr():
            from infrastructure.cache_manager import SystemCacheManager
            transport = c.get('transport')
            return SystemCacheManager(transport)
        c.register_factory('system_cache_manager', _make_cache_mgr)
        
        # parser
        c.register_singleton('response_parser', ResponseParser())
        # tx manager
        c.register_singleton('tx_manager', TransactionManager(db))
        # small services
        c.register_singleton('message_status', MessageStatusService(db))
        c.register_singleton('session_meta', SessionMetaService(db))
        c.register_singleton('profile_svc', ProfileService(db))
        # orchestrator
        def _make_orchestrator():
            return ChatOrchestrator(
                db=c.get('db'),
                gemini_client=c.get('gemini_client'),  # 使用新架构
                response_parser=c.get('response_parser'),
                tx_manager=c.get('tx_manager'),
                msg_service=c.get('message_status'),
                session_meta_svc=c.get('session_meta'),
                profile_svc=c.get('profile_svc'),
                system_cache_mgr=c.get('system_cache_manager'),
            )
        c.register_factory('chat_orchestrator', _make_orchestrator)

        # welcome service
        def _make_welcome():
            return WelcomeService(
                db=c.get('db'),
                gemini_client=c.get('gemini_client'),  # 使用新架构
                tx_manager=c.get('tx_manager'),
                response_parser=c.get('response_parser'),
                system_cache_mgr=c.get('system_cache_manager'),
            )
        c.register_factory('welcome_service', _make_welcome)
        return c

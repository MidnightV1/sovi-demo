from __future__ import annotations
from typing import Optional, Dict, Any


class SessionMetaService:
    """
    处理会话标题与摘要的更新规则。
    - 仅当解析出 Session_Meta.title 且当前标题为空/默认"新对话"等情况下才更新标题。
    - 摘要更新留作后续扩展（当前不强制）。
    """

    def __init__(self, db):
        self._db = db

    def update_title_if_needed(self, conversation_id: int, parsed_session_meta: Optional[Dict[str, Any]]):
        if not parsed_session_meta:
            return
        title = parsed_session_meta.get('title')
        if not title:
            return
        current_title = self._db.get_conversation_title(conversation_id)
        if not current_title or current_title.startswith('新对话') or current_title in ('无标题对话', '新对话'):
            self._db.update_conversation_title(conversation_id, title)

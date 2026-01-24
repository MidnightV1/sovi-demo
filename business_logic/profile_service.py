from __future__ import annotations
from typing import Optional, Dict, Any


class ProfileService:
    """
    处理解析出的用户画像更新。
    仅当 profile_update.profile_update_required=True 且有 updated_user_profile 时保存。
    """

    def __init__(self, db):
        self._db = db

    def save_if_needed(self, user_id: int, parsed_profile_update: Optional[Dict[str, Any]]):
        if not parsed_profile_update:
            return
        if not parsed_profile_update.get('profile_update_required'):
            return
        updated = parsed_profile_update.get('updated_user_profile')
        if not updated:
            return
        self._db.save_user_profile(user_id, updated)

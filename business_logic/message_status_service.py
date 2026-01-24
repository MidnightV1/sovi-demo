from __future__ import annotations
from typing import Optional, Dict, Any
from tools.utils import TimeUtils


class MessageStatusService:
    """
    封装用户消息的状态流转，避免孤儿消息：
    - create_pending_user_message: 先写入PENDING
    - finalize_success: 在AI消息与相关元数据成功保存后，标记SUCCESS
    - mark_failed: 异常时标记FAILED
    说明：实际AI消息、元数据、标题/画像更新由上层编排器在短事务中完成。
    """

    def __init__(self, db):
        self._db = db

    def create_pending_user_message(
        self,
        conversation_id: int,
        user_id: int,
        content: str,
        round_num: int,
        image_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        message = {
            'conversation_id': conversation_id,
            'role': 'user',
            'content': content,
            'round_num': round_num,
            'created_at': TimeUtils.format_iso_utc(TimeUtils.utc_now()),
            'image_data': image_path,
            'user_id': user_id,
            'send_status': 'pending',
        }
        message_id = self._db.save_message(
            conversation_id=conversation_id,
            user_id=user_id,
            role='user',
            origin_content=content,
            round_num=round_num,
            view_content=content,
            working_content=content,
            image_url=image_path,
            send_status='pending',
        )
        message['message_id'] = message_id
        return message

    def finalize_success(self, user_message_id: int) -> bool:
        return self._db.update_message_status(user_message_id, 'success')

    def mark_failed(self, user_message_id: int) -> bool:
        return self._db.update_message_status(user_message_id, 'failed')

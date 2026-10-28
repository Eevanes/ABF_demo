import asyncio
import hashlib
import inspect
import json
from typing import Any, Protocol

from arena.observability.audit import OperationJournal
from arena.store import now_iso


class Notifier(Protocol):
    async def send(self, recipient: str, text: str, idempotency_key: str) -> dict[str, Any]: ...


class NotificationOutbox:
    """Durable at-least-once delivery; adapters must implement provider deduplication.

    A boolean or an HTTP success without a platform receipt is not delivery proof.
    `sent` proves provider acceptance; recipient confirmation is a separate step.
    """

    def __init__(self, journal: OperationJournal):
        self.journal = journal
        self._dispatch_lock = asyncio.Lock()

    def enqueue(self, notification_id: str, recipient: str, text: str, ticket_id: str) -> dict:
        if not notification_id or not recipient or not text:
            raise ValueError("通知必须包含幂等键、接收人和正文")
        digest = hashlib.sha256(
            json.dumps([recipient, text, ticket_id], ensure_ascii=False).encode()
        ).hexdigest()
        old = self.journal.get_notification(notification_id)
        if old:
            if old["request_hash"] != digest:
                raise ValueError("通知幂等键已用于不同内容")
            return old
        item = {
            "notification_id": notification_id,
            "ticket_id": ticket_id,
            "recipient": recipient,
            "text": text,
            "request_hash": digest,
            "status": "queued",
            "receipt": None,
            "attempts": 0,
            "last_error": None,
            "updated_at": now_iso(),
        }
        self.journal.save_notification(item)
        self.journal.audit("arena", ticket_id, "notification_queued", new_status="queued")
        return item

    async def dispatch(self, notification_id: str, notifier: Notifier) -> dict:
        async with self._dispatch_lock:
            return await self._dispatch(notification_id, notifier)

    async def _dispatch(self, notification_id: str, notifier: Notifier) -> dict:
        item = self.journal.get_notification(notification_id)
        if item is None:
            raise ValueError("找不到通知")
        if item["status"] in ("sent", "acknowledged"):
            return item
        item["attempts"] += 1
        # Persist attempt before side effect. A crash retries with the SAME provider key.
        self.journal.save_notification(item)
        try:
            outcome = notifier.send(item["recipient"], item["text"], notification_id)
            result = await outcome if inspect.isawaitable(outcome) else outcome
            if (
                not isinstance(result, dict)
                or result.get("accepted") is not True
                or not result.get("receipt")
            ):
                raise ValueError("missing_platform_receipt")
            item.update(status="sent", receipt=result["receipt"], last_error=None)
        except Exception as exc:
            # Exception messages can contain API credentials. Persist only safe class names.
            item.update(status="failed", last_error=type(exc).__name__)
        item["updated_at"] = now_iso()
        self.journal.save_notification(item)
        self.journal.audit("arena", item["ticket_id"], "notification_attempt", new_status=item["status"])
        return item

    def acknowledge(self, notification_id: str, userid: str) -> dict:
        item = self.journal.get_notification(notification_id)
        if not item or item["recipient"] != userid:
            raise PermissionError("仅通知接收人可确认")
        if item["status"] not in ("sent", "acknowledged") or not item["receipt"]:
            raise ValueError("尚无平台投递回执")
        item.update(status="acknowledged", updated_at=now_iso())
        self.journal.save_notification(item)
        self.journal.audit(userid, item["ticket_id"], "notification_ack", new_status="acknowledged")
        return item

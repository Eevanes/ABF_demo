import pytest

from arena.observability.audit import OperationJournal
from arena.workflows.outbox import NotificationOutbox


class FakeNotifier:
    def __init__(self, result):
        self.result, self.keys = result, []

    async def send(self, recipient, text, idempotency_key):
        self.keys.append(idempotency_key)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.mark.asyncio
async def test_failed_delivery_retry_receipt_and_duplicate_suppression(tmp_path):
    journal = OperationJournal(tmp_path / "operations.sqlite3")
    try:
        outbox = NotificationOutbox(journal)
        item = outbox.enqueue("n1", "worker", "工单待处理", "T-1")
        assert item["status"] == "queued"
        notifier = FakeNotifier({"accepted": True})
        assert (await outbox.dispatch("n1", notifier))["status"] == "failed"
        notifier.result = {"accepted": True, "receipt": "provider-message-id"}
        assert (await outbox.dispatch("n1", notifier))["status"] == "sent"
        await outbox.dispatch("n1", notifier)
        assert notifier.keys == ["n1", "n1"]
        with pytest.raises(PermissionError):
            outbox.acknowledge("n1", "someone")
        assert outbox.acknowledge("n1", "worker")["status"] == "acknowledged"
        with pytest.raises(ValueError, match="幂等键"):
            outbox.enqueue("n1", "worker", "different", "T-1")
    finally:
        journal.close()


@pytest.mark.asyncio
async def test_exception_is_sanitized_and_queue_survives_restart(tmp_path):
    path = tmp_path / "operations.sqlite3"
    journal = OperationJournal(path)
    NotificationOutbox(journal).enqueue("n1", "worker", "工单待处理", "T-1")
    journal.close()
    reopened = OperationJournal(path)
    try:
        outbox = NotificationOutbox(reopened)
        result = await outbox.dispatch("n1", FakeNotifier(RuntimeError("sensitive-credential")))
        assert result["status"] == "failed"
        assert result["last_error"] == "RuntimeError"
        assert "sensitive-credential" not in str(reopened.list_notifications())
        with pytest.raises(ValueError, match="回执"):
            outbox.acknowledge("n1", "worker")
    finally:
        reopened.close()


@pytest.mark.asyncio
async def test_concurrent_dispatch_keeps_one_platform_send(tmp_path):
    import asyncio

    journal = OperationJournal(tmp_path / "operations.sqlite3")
    try:
        outbox = NotificationOutbox(journal)
        outbox.enqueue("n1", "worker", "待接单", "T-1")
        notifier = FakeNotifier({"accepted": True, "receipt": "platform-receipt"})
        results = await asyncio.gather(*(outbox.dispatch("n1", notifier) for _ in range(10)))
        assert notifier.keys == ["n1"]
        assert all(item["status"] == "sent" for item in results)
    finally:
        journal.close()

from arena.observability.audit import OperationJournal
from arena.workflows.outbox import NotificationOutbox
from arena.workflows.runner import TicketWorker
from arena.workflows.tickets import Actor, TicketService


async def test_no_provider_queues_without_claiming_delivery(tmp_path):
    journal = OperationJournal(tmp_path / "events.sqlite3")
    try:
        tickets = TicketService(journal, journal, owner_userid="owner")
        item = tickets.create(Actor("requester", "participant"), "request", "提交异常")
        worker = TicketWorker(tickets, NotificationOutbox(journal))
        for _ in range(2):
            report = await worker.tick()
            assert report["queued"] == 1 and report["sent"] == 0
        assert len(journal.list_notifications()) == 1
        assert journal.get_ticket(item["ticket_id"])["notify_status"] == "queued"
    finally:
        journal.close()


async def test_provider_receipt_recorded_and_not_resent(tmp_path):
    journal = OperationJournal(tmp_path / "events.sqlite3")
    class Provider:
        calls = 0
        async def send(self, recipient, text, key):
            self.calls += 1
            return {"accepted": True, "receipt": "mock-provider-receipt"}
    try:
        provider = Provider()
        tickets = TicketService(journal, journal, owner_userid="owner")
        item = tickets.create(Actor("requester", "participant"), "request", "提交异常")
        worker = TicketWorker(tickets, NotificationOutbox(journal), provider)
        assert (await worker.tick())["sent"] == 1
        assert (await worker.tick())["sent"] == 0
        assert provider.calls == 1
        assert journal.get_ticket(item["ticket_id"])["notify_receipt"] == "mock-provider-receipt"
    finally:
        journal.close()

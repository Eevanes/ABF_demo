"""Deterministic DRI escalation and durable notification intents."""

import asyncio
import hashlib

from arena.workflows.outbox import NotificationOutbox, Notifier
from arena.workflows.tickets import TicketService


class TicketWorker:
    def __init__(self, tickets: TicketService, outbox: NotificationOutbox, notifier: Notifier | None = None):
        self.tickets, self.outbox, self.notifier = tickets, outbox, notifier

    async def tick(self) -> dict:
        escalated = await asyncio.to_thread(self.tickets.escalate_due)
        queued, sent, failed = 0, 0, 0
        for item in await asyncio.to_thread(self.tickets.backend.list_tickets):
            if item["status"] in ("closed", "resolved") or not item["assigned_userid"]:
                continue
            if item["notify_status"] in ("sent", "acknowledged"):
                continue
            identifier = hashlib.sha256(
                f"{item['ticket_id']}:{item['assigned_userid']}:{item['due_at']}".encode()
            ).hexdigest()
            intent = self.outbox.enqueue(
                identifier,
                item["assigned_userid"],
                f"Arena 工单 {item['ticket_id']}：{item['summary']}；请在独立认证入口接单。",
                item["ticket_id"],
            )
            if self.notifier is not None:
                intent = await self.outbox.dispatch(identifier, self.notifier)
            await asyncio.to_thread(self.tickets.record_notification, item["ticket_id"], intent)
            queued += intent["status"] == "queued"
            sent += intent["status"] == "sent"
            failed += intent["status"] == "failed"
        return {
            "escalated": len(escalated),
            "queued": queued,
            "sent": sent,
            "failed": failed,
            "provider_attached": self.notifier is not None,
        }

    async def run(self, interval: float = 60):
        while True:
            await self.tick()
            await asyncio.sleep(interval)

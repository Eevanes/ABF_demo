import json
import sqlite3
from pathlib import Path
from typing import Any

from arena.store import now_iso


class OperationJournal:
    """Persistent audit/outbox journal, not a second copy of the business registry.

    SQLite ticket rows are an explicit offline/test adapter only. Production uses
    SmartSheetRegistry as TicketService.backend and this journal for audit/outbox.
    """

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS audit_events (
            event_id INTEGER PRIMARY KEY, time TEXT, actor TEXT, entity_id TEXT,
            action TEXT, old_status TEXT, new_status TEXT, reason TEXT);
        CREATE TABLE IF NOT EXISTS offline_tickets (ticket_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS notification_outbox (notification_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS improvement_proposals (proposal_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        """)

    def audit(
        self,
        actor: str,
        entity_id: str,
        action: str,
        old_status: str = "",
        new_status: str = "",
        reason: str = "",
    ) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO audit_events(time,actor,entity_id,action,old_status,new_status,reason) VALUES(?,?,?,?,?,?,?)",
                (now_iso(), actor, entity_id, action, old_status, new_status, reason),
            )

    def events(self, entity_id: str) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.db.execute(
                "SELECT * FROM audit_events WHERE entity_id=? ORDER BY event_id", (entity_id,)
            )
        ]

    def get_ticket(self, ticket_id: str) -> dict[str, Any] | None:
        row = self.db.execute(
            "SELECT payload FROM offline_tickets WHERE ticket_id=?", (ticket_id,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def list_tickets(self) -> list[dict[str, Any]]:
        return [
            json.loads(row[0])
            for row in self.db.execute("SELECT payload FROM offline_tickets ORDER BY ticket_id")
        ]

    def save_ticket(self, item: dict[str, Any], expected_status: str | None = None) -> None:
        with self.db:
            old = self.get_ticket(item["ticket_id"])
            if expected_status is not None and (not old or old["status"] != expected_status):
                raise ValueError("工单状态已变化，请重新读取")
            self.db.execute(
                "INSERT OR REPLACE INTO offline_tickets VALUES(?,?)",
                (item["ticket_id"], json.dumps(item, ensure_ascii=False)),
            )

    def get_notification(self, notification_id: str) -> dict[str, Any] | None:
        row = self.db.execute(
            "SELECT payload FROM notification_outbox WHERE notification_id=?", (notification_id,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def list_notifications(self) -> list[dict[str, Any]]:
        return [
            json.loads(row[0])
            for row in self.db.execute("SELECT payload FROM notification_outbox ORDER BY notification_id")
        ]

    def save_notification(self, item: dict[str, Any]) -> None:
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO notification_outbox VALUES(?,?)",
                (item["notification_id"], json.dumps(item, ensure_ascii=False)),
            )

    def close(self) -> None:
        self.db.close()

    def save_proposal(self, item: dict[str, Any]) -> None:
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO improvement_proposals VALUES(?,?)",
                (item["proposal_id"], json.dumps(item, ensure_ascii=False)),
            )

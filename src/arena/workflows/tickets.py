from __future__ import annotations

import builtins
import hashlib
import json
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Any, Callable, Protocol

from arena.observability.audit import OperationJournal
from arena.store import now_iso


@dataclass(frozen=True)
class Actor:
    """Construct only from authenticated server identity, never chat arguments."""

    userid: str
    role: str


class TicketBackend(Protocol):
    def get_ticket(self, ticket_id: str) -> dict[str, Any] | None: ...
    def list_tickets(self) -> list[dict[str, Any]]: ...
    def save_ticket(self, item: dict[str, Any], expected_status: str | None = None) -> None: ...


TRANSITIONS = {
    "new": {"assigned", "needs_review"},
    "assigned": {"acknowledged", "escalated", "needs_review"},
    "acknowledged": {"in_progress", "waiting_input", "needs_review"},
    "in_progress": {"resolved", "waiting_input", "needs_review"},
    "waiting_input": {"in_progress", "needs_review", "escalated"},
    "needs_review": {"assigned", "in_progress", "escalated"},
    "escalated": {"acknowledged", "assigned", "needs_review"},
    "resolved": {"closed", "needs_review"},
    "closed": set(),
}


def serialized(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self.lock:
            return method(self, *args, **kwargs)

    return wrapped


class TicketService:
    """Single-instance deterministic state machine; cloud CAS is best effort.

    Registry is the authoritative ticket source. Local journal stores audit events
    and notification intents. Pass OperationJournal as backend ONLY for offline
    rehearsals; the production composition must inject SmartSheetRegistry.
    """

    def __init__(
        self,
        backend: TicketBackend,
        journal: OperationJournal,
        duty_lookup: Callable[[str], dict[str, Any] | None] | None = None,
        owner_userid: str = "",
        ack_timeout_minutes: int = 30,
    ):
        self.backend, self.journal = backend, journal
        self.lock = threading.RLock()
        self.duty_lookup = duty_lookup or (lambda category: None)
        self.owner_userid = owner_userid
        if ack_timeout_minutes <= 0:
            raise ValueError("接单超时必须为正数")
        self.ack_timeout_minutes = ack_timeout_minutes

    @staticmethod
    def _authenticated(actor: Actor) -> None:
        if not actor.userid or actor.role not in ("participant", "staff", "admin"):
            raise PermissionError("缺少可信操作者身份")

    @staticmethod
    def _evidence(urls: list[str] | None) -> list[str]:
        result = urls or []
        if not isinstance(result, list) or any(
            not isinstance(url, str) or not url.startswith("https://") for url in result
        ):
            raise ValueError("证据须为 HTTPS 链接")
        return result

    def _save(self, actor: str, item: dict, action: str, old_status: str = "", reason: str = "") -> dict:
        item["last_updated_at"] = now_iso()
        self.backend.save_ticket(item, expected_status=old_status or None)
        self.journal.audit(actor, item["ticket_id"], action, old_status, item["status"], reason)
        return item

    @serialized
    def create(
        self,
        actor: Actor,
        request_id: str,
        summary: str,
        category: str = "其他",
        work_id: str | None = None,
        evidence_urls: builtins.list[str] | None = None,
        priority: str = "normal",
    ) -> dict:
        self._authenticated(actor)
        if not request_id or len(request_id) > 128 or not summary.strip() or len(summary) > 2000:
            raise ValueError("需要有效请求幂等键和1至2000字问题摘要")
        if priority not in ("low", "normal", "high", "urgent"):
            raise ValueError("未知优先级")
        # Participant cannot dictate urgency or an arbitrary organizational category.
        if actor.role == "participant" and (priority != "normal" or category != "其他"):
            raise PermissionError("选手只能提交普通问题")
        evidence = self._evidence(evidence_urls)
        ticket_id = "T-" + uuid.uuid5(uuid.NAMESPACE_URL, actor.userid + ":" + request_id).hex
        digest = hashlib.sha256(
            json.dumps([summary, category, work_id, evidence, priority], ensure_ascii=False).encode()
        ).hexdigest()
        existing = self.backend.get_ticket(ticket_id)
        if existing:
            if existing["request_hash"] != digest:
                raise ValueError("请求幂等键已用于不同工单内容")
            return existing
        duty = self.duty_lookup(category) or self.duty_lookup("其他") or {}
        assignee = duty.get("userid") or self.owner_userid
        now = datetime.now(timezone.utc)
        item = {
            "ticket_id": ticket_id,
            "request_id": request_id,
            "request_hash": digest,
            "created_at": now.isoformat(),
            "source": "mcp",
            "requester_userid": actor.userid,
            "work_id": work_id,
            "category": category,
            "priority": priority,
            "summary": summary.strip(),
            "evidence_urls": evidence,
            "assigned_userid": assignee,
            "backup_userid": duty.get("backup_userid", ""),
            "assignment_rule_version": "duty-v1",
            "status": "assigned" if assignee else "needs_review",
            "ack_at": None,
            "due_at": (now + timedelta(minutes=self.ack_timeout_minutes)).isoformat(),
            "resolved_at": None,
            "resolution": "",
            "feedback_id": None,
            "notify_status": "queued",
            "notify_receipt": None,
            "last_updated_at": now.isoformat(),
        }
        return self._save(actor.userid, item, "create")

    def get(self, actor: Actor, ticket_id: str) -> dict:
        self._authenticated(actor)
        item = self.backend.get_ticket(ticket_id)
        if not item:
            raise ValueError("找不到工单")
        if actor.role != "admin" and actor.userid not in (item["requester_userid"], item["assigned_userid"]):
            raise PermissionError("无权查看其他人的工单")
        return item

    def list(self, actor: Actor) -> list[dict]:
        self._authenticated(actor)
        return [
            item
            for item in self.backend.list_tickets()
            if actor.role == "admin" or actor.userid in (item["requester_userid"], item["assigned_userid"])
        ]

    @serialized
    def transition(
        self,
        actor: Actor,
        ticket_id: str,
        status: str,
        resolution: str = "",
        evidence_urls: builtins.list[str] | None = None,
    ) -> dict:
        item = self.get(actor, ticket_id)
        old = item["status"]
        if status == old:
            return item
        if status not in TRANSITIONS.get(old, set()):
            raise ValueError("不允许的工单状态转换")
        if status == "closed":
            if actor.role != "admin" and actor.userid != item["requester_userid"]:
                raise PermissionError("需请求人或管理员确认结案")
        elif actor.role != "admin" and (actor.role != "staff" or actor.userid != item["assigned_userid"]):
            raise PermissionError("仅当前负责人或管理员可处理")
        if status in ("assigned", "acknowledged") and not item["assigned_userid"]:
            raise ValueError("工单没有负责人")
        if status == "acknowledged":
            item["ack_at"] = now_iso()
        if status == "resolved":
            evidence = self._evidence(evidence_urls)
            if not resolution.strip() or not evidence:
                raise ValueError("解决工单必须提供处理说明和证据")
            item.update(resolution=resolution.strip(), evidence_urls=evidence, resolved_at=now_iso())
        item["status"] = status
        return self._save(actor.userid, item, "transition", old, resolution)

    @serialized
    def assign(self, actor: Actor, ticket_id: str, userid: str, reason: str) -> dict:
        item = self.get(actor, ticket_id)
        if actor.role != "admin":
            raise PermissionError("人工改派须管理员确认")
        if not userid or not reason.strip() or item["status"] in ("closed", "resolved"):
            raise ValueError("改派需要负责人、原因及未结案工单")
        old = item["status"]
        item.update(
            assigned_userid=userid,
            status="assigned",
            ack_at=None,
            notify_status="queued",
            notify_receipt=None,
            due_at=(datetime.now(timezone.utc) + timedelta(minutes=self.ack_timeout_minutes)).isoformat(),
        )
        return self._save(actor.userid, item, "assign", old, reason)

    @serialized
    def escalate_due(self, now: datetime | None = None) -> builtins.list[dict]:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError("升级时钟必须包含时区")
        results = []
        for item in self.backend.list_tickets():
            if (
                item["status"] not in ("assigned", "escalated")
                or item["ack_at"]
                or datetime.fromisoformat(item["due_at"]) > now
            ):
                continue
            candidates = (item.get("backup_userid"), self.owner_userid)
            target = next((value for value in candidates if value and value != item["assigned_userid"]), "")
            if not target:
                continue
            old = item["status"]
            # Consume backup so another timeout progresses to fixed Owner, never loops.
            item.update(
                assigned_userid=target,
                backup_userid="",
                status="escalated",
                notify_status="queued",
                notify_receipt=None,
                due_at=(now + timedelta(minutes=self.ack_timeout_minutes)).isoformat(),
            )
            results.append(self._save("arena", item, "timeout_escalation", old, "接单超时"))
        return results

    @serialized
    def record_notification(self, ticket_id: str, notification: dict) -> dict:
        item = self.backend.get_ticket(ticket_id)
        if (
            not item
            or notification.get("ticket_id") != ticket_id
            or notification.get("recipient") != item["assigned_userid"]
        ):
            raise ValueError("通知与当前工单负责人不一致")
        state = notification.get("status")
        if state not in ("queued", "sent", "acknowledged", "failed"):
            raise ValueError("未知通知状态")
        if state in ("sent", "acknowledged") and not notification.get("receipt"):
            raise ValueError("投递成功必须有平台回执")
        item.update(notify_status=state, notify_receipt=notification.get("receipt"))
        return self._save("arena", item, "notification", item["status"])

    @serialized
    def propose_change(
        self, actor: Actor, feedback_id: str, summary: str, issue_url: str | None = None
    ) -> dict:
        self._authenticated(actor)
        if actor.role != "admin":
            raise PermissionError("改进建议须由Owner审查")
        if not feedback_id or not summary.strip() or len(summary) > 2000:
            raise ValueError("改进建议需要反馈编号和摘要")
        if issue_url is not None:
            self._evidence([issue_url])
        # Only a draft artifact. This never creates an external Issue or publishes a rule.
        item: dict[str, Any] = {
            "proposal_id": "P-" + uuid.uuid5(uuid.NAMESPACE_URL, feedback_id + summary).hex,
            "feedback_id": feedback_id,
            "summary": summary.strip(),
            "issue_url": issue_url,
            "status": "proposed",
            "approved_by": None,
            "published_at": None,
            "created_by": actor.userid,
            "created_at": now_iso(),
        }
        self.journal.save_proposal(item)
        self.journal.audit(
            actor.userid, item["proposal_id"], "propose_change", new_status="proposed", reason=feedback_id
        )
        return item

from datetime import datetime, timedelta, timezone

import pytest

from arena.observability.audit import OperationJournal
from arena.workflows.tickets import Actor, TicketService


@pytest.fixture
def workflow(tmp_path):
    journal = OperationJournal(tmp_path / "operations.sqlite3")
    duty = {"userid": "volunteer", "backup_userid": "backup"}
    service = TicketService(journal, journal, lambda category: duty.copy(), "owner")
    yield service, journal, duty
    journal.close()


def create(service, request_id="req"):
    return service.create(Actor("requester", "participant"), request_id, "提交后找不到版本")


def test_retry_and_conflicting_request(workflow):
    service, journal, _ = workflow
    item = create(service)
    assert create(service) == item
    assert len(journal.list_tickets()) == 1
    with pytest.raises(ValueError, match="幂等键"):
        service.create(Actor("requester", "participant"), "req", "另一个问题")


def test_missing_duty_falls_back_to_owner_and_no_owner_needs_review(tmp_path):
    journal = OperationJournal(tmp_path / "operations.sqlite3")
    try:
        service = TicketService(journal, journal, owner_userid="owner")
        assert create(service)["assigned_userid"] == "owner"
        service.owner_userid = ""
        assert create(service, "second")["status"] == "needs_review"
    finally:
        journal.close()


def test_different_requester_and_staff_cannot_read_or_ack(workflow):
    service, _, _ = workflow
    item = create(service)
    for actor in (Actor("another", "participant"), Actor("another", "staff")):
        assert service.list(actor) == []
        with pytest.raises(PermissionError):
            service.get(actor, item["ticket_id"])
        with pytest.raises(PermissionError):
            service.transition(actor, item["ticket_id"], "acknowledged")
    with pytest.raises(PermissionError):
        service.transition(Actor("requester", "participant"), item["ticket_id"], "acknowledged")


def test_resolve_needs_evidence_and_requester_closes(workflow):
    service, journal, _ = workflow
    item = create(service)
    worker = Actor("volunteer", "staff")
    with pytest.raises(ValueError, match="转换"):
        service.transition(worker, item["ticket_id"], "resolved")
    service.transition(worker, item["ticket_id"], "acknowledged")
    service.transition(worker, item["ticket_id"], "in_progress")
    with pytest.raises(ValueError, match="证据"):
        service.transition(worker, item["ticket_id"], "resolved", "已修复")
    service.transition(worker, item["ticket_id"], "resolved", "核对版本并恢复登记", ["https://example.test/evidence"])
    with pytest.raises(PermissionError):
        service.transition(worker, item["ticket_id"], "closed")
    result = service.transition(Actor("requester", "participant"), item["ticket_id"], "closed")
    assert result["resolved_at"]
    assert len(journal.events(item["ticket_id"])) == 5


def test_timeout_escalates_backup_then_owner_without_loop(workflow):
    service, _, _ = workflow
    item = create(service)
    now = datetime.now(timezone.utc) + timedelta(hours=1)
    first = service.escalate_due(now)
    assert first[0]["assigned_userid"] == "backup"
    assert service.escalate_due(now + timedelta(hours=1))[0]["assigned_userid"] == "owner"
    assert service.escalate_due(now + timedelta(hours=2)) == []
    with pytest.raises(PermissionError):
        service.transition(Actor("volunteer", "staff"), item["ticket_id"], "acknowledged")


def test_ack_prevents_timeout_and_shift_change_does_not_drop_ticket(workflow):
    service, journal, duty = workflow
    item = create(service)
    duty["userid"] = "next-volunteer"
    # Existing open ticket keeps its one current DRI across a shift change.
    assert journal.get_ticket(item["ticket_id"])["assigned_userid"] == "volunteer"
    assert create(service, "second")["assigned_userid"] == "next-volunteer"
    service.transition(Actor("volunteer", "staff"), item["ticket_id"], "acknowledged")
    assert all(t["ticket_id"] != item["ticket_id"] for t in service.escalate_due(datetime.now(timezone.utc) + timedelta(days=1)))


def test_admin_reassignment_requires_reason_and_records_operator(workflow):
    service, journal, _ = workflow
    item = create(service)
    with pytest.raises(PermissionError):
        service.assign(Actor("volunteer", "staff"), item["ticket_id"], "new", "交接")
    with pytest.raises(ValueError):
        service.assign(Actor("owner", "admin"), item["ticket_id"], "new", "")
    result = service.assign(Actor("owner", "admin"), item["ticket_id"], "new", "人工确认交接")
    assert result["assigned_userid"] == "new"
    assert journal.events(item["ticket_id"])[-1]["actor"] == "owner"


def test_receipt_is_required_and_old_assignee_notification_rejected(workflow):
    service, _, _ = workflow
    item = create(service)
    notification = {"ticket_id": item["ticket_id"], "recipient": "volunteer", "status": "sent"}
    with pytest.raises(ValueError, match="回执"):
        service.record_notification(item["ticket_id"], notification)
    notification.update(status="failed")
    assert service.record_notification(item["ticket_id"], notification)["notify_status"] == "failed"
    notification.update(status="sent", receipt="platform-message-1")
    assert service.record_notification(item["ticket_id"], notification)["notify_receipt"]
    service.assign(Actor("owner", "admin"), item["ticket_id"], "other", "重新派单")
    with pytest.raises(ValueError, match="负责人"):
        service.record_notification(item["ticket_id"], notification)


def test_journal_restart_keeps_tickets_and_audit(tmp_path):
    path = tmp_path / "operations.sqlite3"
    journal = OperationJournal(path)
    item = create(TicketService(journal, journal, owner_userid="owner"))
    journal.close()
    reopened = OperationJournal(path)
    try:
        assert reopened.get_ticket(item["ticket_id"])["status"] == "assigned"
        assert len(reopened.events(item["ticket_id"])) == 1
    finally:
        reopened.close()


def test_missing_identity_priority_and_plain_http_evidence_rejected(workflow):
    service, _, _ = workflow
    with pytest.raises(PermissionError):
        service.create(Actor("", "staff"), "a", "问题")
    with pytest.raises(PermissionError):
        service.create(Actor("requester", "participant"), "a", "问题", priority="urgent")
    with pytest.raises(ValueError):
        service.create(Actor("requester", "participant"), "a", "问题", evidence_urls=["http://example.test"])


def test_concurrent_duplicate_and_proposal_is_only_draft(workflow):
    from concurrent.futures import ThreadPoolExecutor

    service, journal, _ = workflow
    with ThreadPoolExecutor(max_workers=4) as pool:
        items = list(pool.map(lambda _: create(service), range(10)))
    assert len({item["ticket_id"] for item in items}) == 1
    assert len(journal.list_tickets()) == 1
    with pytest.raises(PermissionError):
        service.propose_change(Actor("volunteer", "staff"), "feedback-1", "补充知识")
    proposal = service.propose_change(Actor("owner", "admin"), "feedback-1", "补充知识")
    assert proposal["status"] == "proposed"
    assert proposal["approved_by"] is None and proposal["published_at"] is None
    assert journal.events(proposal["proposal_id"])[0]["reason"] == "feedback-1"

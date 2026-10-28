import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

from arena.adapters.smartsheet_registry import RegistryError, SmartSheetRegistry, json_text, text_list


class Credentials:
    def authenticate(self, key):
        return {"id": "H-001"} if key == "local-secret" else None

    def bind_key(self, work_id, key):
        pass


class FakeCLI:
    def __init__(self):
        self.rows = {title: [] for title in ("作品", "版本", "值班", "反馈", "工单")}
        self.calls = []
        self.fail_pointer_once = False
        self.page_size = 1000
        self.sequence = 0

    def call(self, *command, payload):
        title = payload["sheet_title"]
        action = command[-1]
        self.calls.append((title, action))
        if action == "list":
            start = payload.get("start", 0)
            page = self.rows[title][start:start + self.page_size]
            return {"records": copy.deepcopy(page), "has_more": start + len(page) < len(self.rows[title]),
                    "next": start + len(page)}
        values = payload["records"][0]["values"]
        assert "密钥哈希" not in values and "key_hash" not in values
        if self.fail_pointer_once and title == "作品":
            self.fail_pointer_once = False
            raise TimeoutError()
        source = payload["records"][0]
        if action == "add":
            self.sequence += 1
            row = {"record_id": f"r{self.sequence}", "values": copy.deepcopy(values)}
            self.rows[title].append(row)
        else:
            row = next(row for row in self.rows[title] if row["record_id"] == source["record_id"])
            row["values"].update(copy.deepcopy(values))
        return {"records": [copy.deepcopy(row)]}


@pytest.fixture
def cloud():
    cli = FakeCLI()
    cli.rows["作品"].append({"record_id": "work-1", "values": {
        "作品ID": "H-001", "队名": "演练队", "作品名": "作品", "最新版本": 0, "状态": "已报名"}})
    registry = SmartSheetRegistry(Credentials(), cli, "sandbox", write_enabled=True)
    return registry, cli


def submission(version=1, submission_id="submit-1"):
    return {"work_id": "H-001", "version": version, "tag": f"H-001/v{version}",
            "commit_sha": f"sha-{version}", "submitted_at": datetime.now(timezone.utc).isoformat(),
            "content_hash": f"hash-{version}", "description": "这是演练版本的说明", "checks": ["通过"],
            "submission_id": submission_id, "source": "files"}


def test_partial_registration_repaired_without_duplicate(cloud):
    registry, cli = cloud
    cli.fail_pointer_once = True
    with pytest.raises(RegistryError, match="transport_unavailable"):
        registry.record_submission("H-001", None, submission())
    assert len(cli.rows["版本"]) == 1
    assert registry.require("H-001")["latest"] == 0
    assert registry.versions("H-001")[0]["registration_status"] == "registration_pending"
    registry.record_submission("H-001", None, submission())
    registry.record_submission("H-001", None, submission())
    assert len(cli.rows["版本"]) == 1
    assert registry.require("H-001")["latest"] == 1
    assert registry.versions("H-001")[0]["registration_status"] == "registered"


def test_conflicts_fail_and_reconcile_never_rewinds_latest(cloud):
    registry, cli = cloud
    first = submission()
    registry.record_submission("H-001", None, first)
    registry.record_submission("H-001", None, submission(2, "submit-2"))
    registry.record_submission("H-001", None, first)
    assert registry.require("H-001")["latest"] == 2
    with pytest.raises(RegistryError, match="tag_conflict"):
        registry.record_submission("H-001", None, first | {"commit_sha": "other-sha"})
    with pytest.raises(RegistryError, match="submission_id_conflict"):
        registry.record_submission("H-001", None, submission(3))
    assert len(cli.rows["版本"]) == 2


def test_cloud_edits_and_revocation_are_read_on_next_request(cloud):
    registry, cli = cloud
    now = datetime.now(timezone.utc)
    cli.rows["值班"] = [{"record_id": "d1", "values": {
        "duty_id": "d1", "开始时间": (now - timedelta(hours=1)).isoformat(),
        "结束时间": (now + timedelta(hours=1)).isoformat(), "事项类别": "其他", "负责人 userid": "old"}}]
    assert registry.on_duty("其他")["userid"] == "old"
    cli.rows["值班"][0]["values"]["负责人 userid"] = "new"
    assert registry.on_duty("其他")["userid"] == "new"
    assert registry.authenticate("local-secret")["id"] == "H-001"
    cli.rows["作品"][0]["values"]["状态"] = "已禁用"
    assert registry.authenticate("local-secret") is None
    assert "local-secret" not in json.dumps(cli.rows)


def test_pagination_duty_conflicts_and_readonly(cloud):
    registry, cli = cloud
    cli.page_size = 1
    cli.rows["作品"].append({"record_id": "work-2", "values": {"作品ID": "H-002", "最新版本": 0}})
    assert len(registry.works()) == 2
    readonly = SmartSheetRegistry(Credentials(), cli, "sandbox")
    with pytest.raises(RegistryError, match="writes_not_enabled"):
        readonly.record_submission("H-001", None, submission())
    now = datetime.now(timezone.utc)
    cli.rows["值班"] = [{"record_id": f"d{i}", "values": {
        "开始时间": (now - timedelta(hours=1)).isoformat(), "结束时间": (now + timedelta(hours=1)).isoformat(),
        "事项类别": "其他", "负责人 userid": f"user-{i}"}} for i in range(2)]
    with pytest.raises(RegistryError, match="overlapping_duty"):
        registry.on_duty("其他")


def test_ticket_idempotency_and_status_conflict(cloud):
    registry, cli = cloud
    item = {"ticket_id": "t1", "request_id": "r1", "request_hash": "hash1", "status": "assigned",
            "summary": "演练工单", "evidence_urls": ["https://example.org/evidence"]}
    registry.save_ticket(item)
    registry.save_ticket(item)
    assert len(registry.list_tickets()) == 1
    assert registry.get_ticket("t1")["evidence_urls"] == ["https://example.org/evidence"]
    registry.save_ticket(item | {"status": "acknowledged"}, expected_status="assigned")
    with pytest.raises(RegistryError, match="ticket_status_conflict"):
        registry.save_ticket(item | {"status": "resolved"}, expected_status="assigned")
    with pytest.raises(RegistryError, match="ticket_request_conflict"):
        registry.save_ticket(item | {"request_hash": "hash2"})


def test_invalid_pagination_and_duplicate_rows_block(cloud):
    registry, cli = cloud
    cli.rows["作品"].append(copy.deepcopy(cli.rows["作品"][0]))
    with pytest.raises(RegistryError, match="invalid_or_duplicate_work_id"):
        registry.works()
    cli.page_size = 0
    with pytest.raises(RegistryError, match="pagination_not_progressing"):
        registry.works()


def test_real_cli_empty_success_omits_records():
    class EmptyCLI:
        def call(self, *command, payload):
            return {"errcode": 0, "errmsg": "ok"}

    registry = SmartSheetRegistry(Credentials(), EmptyCLI(), "sandbox")
    assert registry.works() == []
    assert registry.versions("H-001") == []


def test_structured_text_survives_richtext_and_legacy_normalization():
    assert text_list([{"type": "text", "text": json_text(["check-a", "check-b"])}]) == ["check-a", "check-b"]
    assert text_list([{"type": "text", "text": "旧版检查说明"}]) == ["旧版检查说明"]
    assert text_list("") == []

"""Explicitly create a separate sandbox; never modifies the current demo tables.

Default is a schema-only dry run. --execute performs real SmartSheet API writes
using local environment credentials, with synthetic data and no outbound message.
"""

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import arena  # noqa: F401 -- initialize Windows platform workaround
from arena.adapters.smartsheet_registry import SCHEMA, RegistryError, SmartSheetRegistry
from arena.wecom_cli import WecomCLI, user_setting


class NoCredentials:
    def authenticate(self, key: str) -> dict | None:
        return None

    def bind_key(self, work_id: str, key: str) -> None:
        raise PermissionError("Sandbox does not manage credentials")


class FailPointerOnce:
    """Inject one failure before the cloud pointer write, without touching Git."""

    def __init__(self, cli: Any):
        self.cli, self.armed = cli, True

    def call(self, *command: str, payload: dict) -> dict:
        if self.armed and command == ("smartsheet", "records", "update") and payload["sheet_title"] == "作品":
            self.armed = False
            raise TimeoutError("sandbox pointer failure")
        return self.cli.call(*command, payload=payload)


def save_sandbox_id(docid: str) -> None:
    # Dedicated configuration only. Never overwrite SMARTSHEET_DOCID/URL.
    name = "ARENA_V03_SMARTSHEET_DOCID"
    if os.name == "nt":
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, docid)
    os.environ[name] = docid


def execute() -> dict:
    cli = WecomCLI()
    day = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    docid = user_setting("ARENA_V03_SMARTSHEET_DOCID")
    if not docid:
        created = cli.call("smartsheet", "create", payload={
            "name": f"ABF · Arena v0.3 验收沙盒 {day}", "sheet_title": "作品", "fields": SCHEMA["作品"]})
        docid = created.get("docid")
        if not docid:
            raise RuntimeError("sandbox_create_missing_docid")
        save_sandbox_id(docid)
        for title, fields in SCHEMA.items():
            if title != "作品":
                cli.call("smartsheet", "sheets", "add", payload={
                    "docid": docid, "sheet_title": title, "type": "add", "fields": fields})
    injected = FailPointerOnce(cli)
    registry = SmartSheetRegistry(NoCredentials(), injected, docid, write_enabled=True)
    registry.verify_schema()

    def upsert(title: str, key: str, value: str, values: dict):
        old = registry._one(registry._records(title), key, value)
        item = {"values": values}
        if old:
            item["record_id"] = old["record_id"]
        return cli.call("smartsheet", "records", "update" if old else "add", payload={
            "docid": docid, "sheet_title": title, "key_type": "field_title", "records": [item]})

    upsert("作品", "作品ID", "H-001", {"作品ID": "H-001", "队名": "v03验收虚构队", "作品名": "Registry演练",
                                     "最新版本": 0, "状态": "已报名"})
    now = datetime.now(timezone.utc)
    item = {"work_id": "H-001", "version": 1, "tag": "H-001/v1", "commit_sha": "sandbox-no-github-write",
            "submitted_at": now.isoformat(), "content_hash": "sandbox-content-not-an-artifact",
            "description": "仅验证真实表格适配器，不代表GitHub作品提交验收", "checks": ["smartsheet-adapter-exercise"],
            "submission_id": "sandbox-submission-1", "source": "smartsheet-adapter-exercise"}
    try:
        registry.record_submission("H-001", None, item)
    except RegistryError as exc:
        if exc.code != "transport_unavailable":
            raise
    else:
        raise RuntimeError("fault_injection_did_not_fire")
    assert len(registry.versions("H-001")) == 1 and registry.require("H-001")["latest"] == 0
    registry.record_submission("H-001", None, item)
    registry.record_submission("H-001", None, item)
    assert len(registry.versions("H-001")) == 1
    assert registry.require("H-001")["latest"] == 1
    assert registry.versions("H-001")[0]["registration_status"] == "registered"
    duty = upsert("值班", "duty_id", "sandbox-duty-1", {"duty_id": "sandbox-duty-1", "事项类别": "其他", "负责人姓名": "虚构负责人",
                       "负责人 userid": "sandbox-owner-a", "status": "active",
                       "开始时间": (now - timedelta(hours=1)).astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S"),
                       "结束时间": (now + timedelta(hours=1)).astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")})
    assert registry.on_duty("其他")["userid"] == "sandbox-owner-a"  # type: ignore[index]
    cli.call("smartsheet", "records", "update", payload={
        "docid": docid, "sheet_title": "值班", "key_type": "field_title", "records": [{
            "record_id": duty["records"][0]["record_id"], "values": {"负责人 userid": "sandbox-owner-b"}}]})
    assert registry.on_duty("其他")["userid"] == "sandbox-owner-b"  # type: ignore[index]
    ticket = {"ticket_id": "sandbox-ticket-1", "request_id": "sandbox-request-1", "request_hash": "sandbox-hash",
              "requester_userid": "sandbox-requester", "summary": "虚构异常", "status": "assigned", "evidence_urls": []}
    registry.save_ticket(ticket)
    registry.save_ticket(ticket)
    registry.save_ticket(ticket | {"status": "acknowledged"}, expected_status="assigned")
    assert len(registry.list_tickets()) == 1
    return {
        "mode": "real_smartsheet_adapter_sandbox", "timestamp": datetime.now(timezone.utc).isoformat(),
        "schema_verified_sheets": 5, "synthetic_works": 1, "versions_after_retries": 1,
        "pointer_failure_recovered": True, "registration_status_readback": "registered",
        "duty_direct_edit_readback": True, "ticket_idempotent_status_readback": True,
        "original_demo_modified": False, "github_artifact_e2e": "not_run",
        "workbuddy_e2e": "not_run", "real_messages_sent": 0,
        "sandbox_id_location": "ARENA_V03_SMARTSHEET_DOCID local user environment",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Create a new isolated cloud sandbox and run real adapter checks")
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({"mode": "dry_run", "creates": "new isolated sandbox only", "sheets": {
            title: len(fields) for title, fields in SCHEMA.items()}, "messages_sent": 0}, ensure_ascii=False))
        return 0
    try:
        report = execute()
    except Exception as exc:
        # Do not serialize API responses or payloads, which may contain real IDs.
        print(json.dumps({"state": "failed", "error_type": type(exc).__name__,
                          "code": exc.code if isinstance(exc, RegistryError) else "check_failed"}))
        return 1
    output = Path(__file__).resolve().parents[1] / "docs" / "v03-cloud-acceptance.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Authoritative SmartSheet Registry, with single-process serialized writers.

No table is automatically created or altered. Operators must provision and verify
the v0.3 schema before enabling writes. Authentication stays with a local authority.
"""

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from arena.ports.registry import CredentialAuthority
from arena.store import now_iso
from arena.wecom_cli import WecomCLI, WecomError, user_setting

WORK_FIELDS = {
    "id": "作品ID", "title": "作品名", "team": "队名", "members": "成员",
    "aliases": "别名", "description": "简介", "latest": "最新版本", "status": "状态",
    "repo_link": "仓库链接",
}
VERSION_FIELDS = {
    "work_id": "作品ID", "version": "版本号", "commit_sha": "commit SHA", "tag": "tag",
    "submitted_at": "提交时间", "source": "来源", "content_hash": "内容哈希",
    "checks": "检查结果", "description": "说明", "submission_id": "submission_id",
    "registration_status": "registration_status", "repo_link": "仓库链接",
    "policy_version": "policy_version",
}
DUTY_FIELDS = {
    "duty_id": "duty_id", "start": "开始时间", "end": "结束时间", "category": "事项类别",
    "name": "负责人姓名", "userid": "负责人 userid", "backup_userid": "backup_userid", "status": "status",
}
FEEDBACK_FIELDS = {
    "id": "feedback_id", "time": "时间", "userid": "提问人 userid", "role": "角色",
    "question": "问题", "answer": "机器人回答", "tools": "使用的工具", "escalated": "是否转人工",
    "assignee": "转给谁", "rating": "评价", "resolution": "处理结果",
    "interaction_id": "interaction_id", "ticket_id": "ticket_id", "policy_version": "policy_version",
    "skill_version": "skill_version", "improvement_issue_id": "improvement_issue_id",
    "answer_source": "answer_source", "question_category": "question_category",
    "answer_confidence_or_abstain": "answer_confidence_or_abstain", "resolved_by": "resolved_by",
}
TICKET_NAMES = (
    "ticket_id", "request_id", "request_hash", "created_at", "source", "requester_userid", "work_id", "category", "priority",
    "summary", "evidence_urls", "assigned_userid", "assignment_rule_version", "status", "ack_at",
    "due_at", "resolved_at", "resolution", "feedback_id", "notify_status", "notify_receipt", "last_updated_at", "backup_userid",
)
# A schema contract, not permission to mutate an existing sheet automatically.
SCHEMA: dict[str, list[dict[str, str]]] = {
    title: [{"field_title": field, "field_type": (
                "number" if field in ("最新版本", "版本号") else
                "date_time" if field in ("开始时间", "结束时间", "提交时间", "时间") else
                "checkbox" if field == "是否转人工" else "url" if field == "仓库链接" else "text")}
            for field in mapping.values()]
    for title, mapping in (("作品", WORK_FIELDS), ("版本", VERSION_FIELDS), ("值班", DUTY_FIELDS),
                           ("反馈", FEEDBACK_FIELDS), ("工单", {name: name for name in TICKET_NAMES}))
}


class RegistryError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False):
        self.code, self.retryable = code, retryable
        super().__init__(f"SmartSheet Registry: {code}")


def plain(value: Any) -> Any:
    if isinstance(value, list) and all(isinstance(part, dict) and "text" in part for part in value):
        return "".join(str(part["text"]) for part in value)
    return value


def decode(values: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    return {key: plain(values.get(field, "")) for key, field in mapping.items()}


def aware_time(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    # Legacy SmartSheet date_time strings are in Asia/Shanghai, not host time.
    return parsed.replace(tzinfo=timezone(timedelta(hours=8))) if parsed.tzinfo is None else parsed


def json_text(value: Any) -> str:
    # The real CLI normalizes bare JSON arrays in text cells. Prefixing keeps the
    # typed JSON payload a text value through its input normalization/readback.
    return "json:" + json.dumps(value, ensure_ascii=False)


def text_list(value: Any) -> list:
    value = plain(value)
    if not value:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value[5:] if str(value).startswith("json:") else value)
    except (ValueError, TypeError):
        # v0.2 human-readable checks, or previously normalized singleton arrays.
        return [str(value)]
    if not isinstance(parsed, list):
        raise RegistryError("invalid_list_field")
    return parsed


class SmartSheetRegistry:
    def __init__(self, credentials: CredentialAuthority, cli: Any = None, docid: str | None = None,
                 *, write_enabled: bool = False):
        self.credentials = credentials
        self.cli = cli if cli is not None else WecomCLI()
        self.docid = docid or user_setting("SMARTSHEET_DOCID")
        if not self.docid:
            raise RegistryError("missing_docid")
        self.write_enabled = write_enabled

    def _call(self, action: str, title: str, **payload: Any) -> dict[str, Any]:
        try:
            result = self.cli.call("smartsheet", "records", action,
                                   payload={"docid": self.docid, "sheet_title": title,
                                            "key_type": "field_title", **payload})
        except WecomError as exc:
            code = str(exc.code)
            if code in {"40014", "42001", "40164", "48002", "60020", "access_denied"}:
                raise RegistryError("permission_or_auth_failed") from None
            raise RegistryError("remote_api_failed", retryable=True) from None
        except (TimeoutError, OSError):
            raise RegistryError("transport_unavailable", retryable=True) from None
        if not isinstance(result, dict):
            raise RegistryError("invalid_response")
        return result

    def _records(self, title: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        start = 0
        for _ in range(100):
            result = self._call("list", title, start=start, limit=1000)
            # The real CLI omits `records` for an empty successful sheet.
            batch = result.get("records", [] if result.get("errcode") == 0 else None)
            if not isinstance(batch, list):
                raise RegistryError("invalid_records")
            rows.extend(batch)
            if result.get("has_more") is False or ("has_more" not in result and len(batch) < 1000):
                return rows
            next_start = result.get("next", start + len(batch))
            if not batch or not isinstance(next_start, int) or next_start <= start:
                raise RegistryError("pagination_not_progressing")
            start = next_start
        raise RegistryError("pagination_limit")

    @staticmethod
    def _one(rows: list[dict[str, Any]], field: str, value: str) -> dict[str, Any] | None:
        matched = [row for row in rows if str(plain(row.get("values", {}).get(field, ""))) == value]
        if len(matched) > 1:
            raise RegistryError("duplicate_business_key")
        return matched[0] if matched else None

    def _write(self, title: str, values: dict[str, Any], existing: dict[str, Any] | None = None) -> None:
        if not self.write_enabled:
            raise RegistryError("writes_not_enabled")
        allowed = {field["field_title"] for field in SCHEMA[title]}
        if not values or not set(values).issubset(allowed):
            raise RegistryError("field_not_allowed")
        values = {name: "" if value is None else value for name, value in values.items()}
        for field in SCHEMA[title]:
            name = field["field_title"]
            if field["field_type"] == "date_time" and values.get(name):
                values[name] = aware_time(values[name]).astimezone(
                    timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
        item = {"values": values}
        if existing:
            item["record_id"] = existing["record_id"]
        result = self._call("update" if existing else "add", title, records=[item])
        records = result.get("records", [])
        if not records or not records[0].get("record_id"):
            raise RegistryError("write_receipt_missing", retryable=True)

    def verify_schema(self) -> dict[str, Any]:
        """Read-only schema check, avoiding automatic changes to user tables."""
        for title, fields in SCHEMA.items():
            result = self.cli.call("smartsheet", "fields", "list",
                                   payload={"docid": self.docid, "sheet_title": title, "limit": 100})
            actual = {field["field_title"] for field in result.get("fields", [])}
            if not {field["field_title"] for field in fields}.issubset(actual):
                raise RegistryError("schema_missing_fields")
        return {"state": "schema_verified", "sheets": list(SCHEMA)}

    def works(self) -> list[dict[str, Any]]:
        works = [decode(row["values"], WORK_FIELDS) for row in self._records("作品")]
        ids = [work["id"] for work in works]
        if len(set(ids)) != len(ids) or any(not re.fullmatch(r"H-\d{3,}", work_id) for work_id in ids):
            raise RegistryError("invalid_or_duplicate_work_id")
        for work in works:
            work["latest"] = int(work["latest"] or 0)
        return sorted(works, key=lambda work: work["id"])

    def get(self, work_id: str) -> dict[str, Any] | None:
        return next((work for work in self.works() if work["id"] == work_id), None)

    def require(self, work_id: str) -> dict[str, Any]:
        work = self.get(work_id)
        if work is None:
            raise ValueError("找不到该作品")
        return work

    def authenticate(self, key: str) -> dict[str, Any] | None:
        identity = self.credentials.authenticate(key)
        if not identity:
            return None
        work = self.get(identity["id"])
        return work if work and work["status"] != "已禁用" else None

    def bind_key(self, work_id: str, key: str) -> None:
        self.require(work_id)
        self.credentials.bind_key(work_id, key)

    def versions(self, work_id: str) -> list[dict[str, Any]]:
        items = [decode(row["values"], VERSION_FIELDS) for row in self._records("版本")
                 if plain(row["values"].get("作品ID")) == work_id]
        for item in items:
            item["version"] = int(item["version"])
            item["checks"] = text_list(item["checks"])
        if len({item["version"] for item in items}) != len(items) or len({item["tag"] for item in items}) != len(items):
            raise RegistryError("duplicate_version")
        return sorted(items, key=lambda item: item["version"])

    def record_submission(self, work_id: str, title: str | None, item: dict[str, Any]) -> None:
        if item.get("work_id", work_id) != work_id or item["tag"] != f"{work_id}/v{item['version']}":
            raise RegistryError("invalid_version_identity")
        if not item.get("submission_id"):
            raise RegistryError("missing_submission_id")
        work_row = self._one(self._records("作品"), "作品ID", work_id)
        if not work_row:
            raise ValueError("找不到该作品")
        rows = self._records("版本")
        existing = self._one(rows, "tag", item["tag"])
        by_submission = self._one(rows, "submission_id", item["submission_id"])
        if by_submission and (not existing or by_submission["record_id"] != existing["record_id"]):
            raise RegistryError("submission_id_conflict")
        if existing:
            old = decode(existing["values"], VERSION_FIELDS)
            if any(str(old[key]) != str(item.get(key, ""))
                   for key in ("submission_id", "commit_sha", "content_hash")):
                raise RegistryError("tag_conflict")
        else:
            collision = any(plain(row["values"].get("作品ID")) == work_id
                            and int(plain(row["values"].get("版本号", 0))) == item["version"] for row in rows)
            if collision:
                raise RegistryError("version_conflict")
            data = {key: value for key, value in item.items() if key in VERSION_FIELDS}
            data.update(work_id=work_id, registration_status="registration_pending")
            data["checks"] = json_text(data.get("checks", []))
            self._write("版本", {VERSION_FIELDS[key]: value for key, value in data.items()})
            existing = self._one(self._records("版本"), "tag", item["tag"])
            if existing is None:
                raise RegistryError("version_readback_missing", retryable=True)
        # These writes are deliberately recoverable rather than claimed transactional.
        # Never roll the latest pointer back when reconciling an older operation.
        current_latest = int(plain(work_row["values"].get("最新版本", 0)) or 0)
        if current_latest <= item["version"]:
            updated = {"最新版本": item["version"], "简介": item["description"], "状态": "已提交"}
            if title is not None:
                updated["作品名"] = title
            if item.get("repo_link"):
                updated["仓库链接"] = item["repo_link"]
            self._write("作品", updated, work_row)
        self._write("版本", {"registration_status": "registered"}, existing)

    def on_duty(self, category: str) -> dict[str, Any] | None:
        current = datetime.now(timezone.utc)
        active = []
        for row in self._records("值班"):
            duty = decode(row["values"], DUTY_FIELDS)
            if duty["category"] == category and duty["status"] in ("", "active", "ACTIVE", "有效"):
                if aware_time(duty["start"]) <= current < aware_time(duty["end"]):
                    active.append(duty)
        if len(active) > 1:
            raise RegistryError("overlapping_duty_requires_review")
        return active[0] if active else None

    def feedback(self, item: dict[str, Any]) -> None:
        existing = self._one(self._records("反馈"), "feedback_id", item["id"])
        data = {key: value for key, value in item.items() if key in FEEDBACK_FIELDS}
        data.setdefault("time", now_iso())
        if not isinstance(data.get("tools", ""), str):
            data["tools"] = json.dumps(data["tools"], ensure_ascii=False)
        self._write("反馈", {FEEDBACK_FIELDS[key]: value for key, value in data.items()}, existing)

    def feedback_report(self) -> list[dict[str, Any]]:
        return [item for row in self._records("反馈")
                if (item := decode(row["values"], FEEDBACK_FIELDS))["rating"] == "踩"
                or item["escalated"] in (True, 1, "true", "是")]

    def get_ticket(self, ticket_id: str) -> dict[str, Any] | None:
        row = self._one(self._records("工单"), "ticket_id", ticket_id)
        if not row:
            return None
        item = decode(row["values"], {name: name for name in TICKET_NAMES})
        for name in ("evidence_urls",):
            item[name] = text_list(item[name])
        return item

    def list_tickets(self) -> list[dict[str, Any]]:
        rows = self._records("工单")
        ids = [str(plain(row["values"].get("ticket_id", ""))) for row in rows]
        if len(set(ids)) != len(ids):
            raise RegistryError("duplicate_ticket_id")
        result = []
        for row in rows:
            item = decode(row["values"], {name: name for name in TICKET_NAMES})
            item["evidence_urls"] = text_list(item["evidence_urls"])
            result.append(item)
        return result

    def save_ticket(self, item: dict[str, Any], expected_status: str | None = None) -> None:
        """Persistence only. Caller must enforce the state machine and serialize writes.

        The sheet API has no atomic CAS. This read/check/write is only protected
        against races when the owning workflow uses one cross-process lease.
        """
        if not item.get("ticket_id") or not set(item).issubset(TICKET_NAMES):
            raise RegistryError("invalid_ticket_fields")
        existing = self._one(self._records("工单"), "ticket_id", item["ticket_id"])
        if expected_status is not None and (
            not existing or plain(existing["values"].get("status")) != expected_status
        ):
            raise RegistryError("ticket_status_conflict")
        if existing and plain(existing["values"].get("request_hash")) != item.get("request_hash"):
            raise RegistryError("ticket_request_conflict")
        data = dict(item)
        if "evidence_urls" in data:
            data["evidence_urls"] = json_text(data["evidence_urls"])
        self._write("工单", data, existing)

    def close(self) -> None:
        # The caller owns the separately supplied local credential authority.
        pass

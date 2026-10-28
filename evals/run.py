"""Offline deterministic service evaluations; these do not test an Agent model."""

import asyncio
import hashlib
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import yaml  # noqa: E402

import arena  # noqa: E402,F401
from arena.observability.audit import OperationJournal  # noqa: E402
from arena.services.policy import PolicyService  # noqa: E402
from arena.services.queries import QueryService  # noqa: E402
from arena.staff_auth import StaffIdentity  # noqa: E402
from arena.store import Store  # noqa: E402
from arena.workflows.tickets import Actor, TicketService  # noqa: E402


def fixture_policy(root: Path, policy_id: str, body: str, roles: list[str]) -> None:
    meta = {
        "policy_id": policy_id, "version": policy_id, "status": "published",
        "effective_at": "2020-01-01T00:00:00+00:00", "approved_by": "eval-fixture-reviewer",
        "source_url": "https://example.test/eval-fixture", "allowed_roles": roles,
        "content_hash": hashlib.sha256(body.encode()).hexdigest(),
    }
    (root / f"{policy_id}.md").write_text("---\n" + yaml.safe_dump(meta) + "---\n" + body, encoding="utf-8")


async def evaluate(case: dict, root: Path) -> bool:
    store = Store(root / "registry.sqlite3")
    journal = OperationJournal(root / "operations.sqlite3")
    try:
        store.register("山海队", "同名作品", "隐私成员")
        store.register("星火队", "同名作品", "另一成员")
        policies = root / "policies"
        policies.mkdir()
        fixture_policy(policies, "public-v1", "提交作品须提供README。", ["public", "staff", "admin"])
        fixture_policy(policies, "sop-v1", "签到岗位处理内部签到流程。", ["staff", "admin"])
        (policies / "draft.md").write_text("未发布草稿", encoding="utf-8")
        policy = PolicyService(policies)
        query = QueryService(store)
        role = case["role"]
        identity = StaffIdentity("operator", "staff" if role == "scoped" else role,
                                 ("H-001",) if role == "scoped" else None)
        op, value, expect = case["operation"], case["input"], case["expect"]
        try:
            if op == "search":
                result = await query.search_works(value, identity)
                if expect == "empty":
                    return not result
                if expect == "multiple":
                    return len(result) == 2
                if expect == "no_members":
                    return bool(result) and all("members" not in row for row in result)
                return bool(result) and result[0]["id"] == expect
            if op == "detail":
                result = await query.get_work(value, identity)
                return bool(result) and result["id"] == expect
            if op in ("policy", "internal"):
                result = policy.search(value, identity, internal=op == "internal")
                return not result if expect == "empty" else bool(result) and result[0]["version"] == expect
            if op == "duty":
                return await query.get_on_duty(value, identity) is None and expect == "empty"
            tickets = TicketService(journal, journal, owner_userid="owner")
            actor = Actor("operator", role)
            if op == "feedback":
                result = tickets.propose_change(actor, "eval-feedback", "补充来源后交审核")
                return result["status"] == expect and result["approved_by"] is None and result["published_at"] is None
            item = tickets.create(Actor("requester", "participant"), "eval-request", "找不到提交版本")
            if value == "duplicate":
                repeated = tickets.create(Actor("requester", "participant"), "eval-request", "找不到提交版本")
                return repeated["ticket_id"] == item["ticket_id"] and len(journal.list_tickets()) == 1
            if value == "conflict":
                tickets.create(Actor("requester", "participant"), "eval-request", "不同问题")
            elif value == "cross":
                tickets.get(actor, item["ticket_id"])
            elif value == "receipt":
                tickets.record_notification(item["ticket_id"], {
                    "ticket_id": item["ticket_id"], "recipient": "owner", "status": "sent"})
            elif value == "timeout":
                # No duty resolves immediately to the fixed Owner.
                tickets.escalate_due(datetime.now(timezone.utc) + timedelta(hours=1))
                return journal.get_ticket(item["ticket_id"])["assigned_userid"] == expect
            elif value == "resolve":
                owner = Actor("owner", "staff")
                tickets.transition(owner, item["ticket_id"], "acknowledged")
                tickets.transition(owner, item["ticket_id"], "in_progress")
                tickets.transition(owner, item["ticket_id"], "resolved", "已处理")
        except PermissionError:
            return expect == "forbidden"
        except ValueError:
            return expect == "rejected"
        return False
    finally:
        store.close()
        journal.close()


async def main() -> int:
    cases = json.loads(Path(__file__).with_name("cases.json").read_text(encoding="utf-8"))
    outcomes = []
    with tempfile.TemporaryDirectory(prefix="arena-evals-") as temp:
        for index, case in enumerate(cases):
            root = Path(temp) / str(index)
            root.mkdir()
            try:
                passed = await evaluate(case, root)
            except Exception as exc:
                outcomes.append({"id": case["id"], "passed": False, "error": type(exc).__name__})
            else:
                outcomes.append({"id": case["id"], "passed": passed})
    print(json.dumps({"mode": "offline-deterministic-services", "agent_model_called": False,
                      "passed": sum(row["passed"] for row in outcomes), "total": len(outcomes),
                      "results": outcomes}, ensure_ascii=False, indent=2))
    return 0 if all(row["passed"] for row in outcomes) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

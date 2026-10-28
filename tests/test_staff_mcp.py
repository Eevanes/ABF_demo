import hashlib
import json

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from arena.services.queries import QueryService
from arena.staff_auth import StaffAuth, StaffIdentity
from arena.staff_mcp import create_staff_app
from arena.walkthrough import running_server, structured


def auth_for(token="independent-test-operator-token", role="staff"):
    return StaffAuth(json.dumps([{
        "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
        "userid": "operator", "role": role, "work_ids": ["H-001"],
    }]))


async def test_staff_protocol_identity_and_scope(bundle):
    settings, registry, _, _ = bundle
    _, team_key = registry.register("山海队", "公开作品", "内部成员甲")
    registry.register("星火队", "另一个作品", "内部成员乙")
    async with running_server(create_staff_app(settings, registry, auth_for())) as url:
        async with httpx.AsyncClient() as http:
            health = (await http.get(url + "/healthz")).json()
            assert health["wecom_sender_verified"] is False
            assert health["writes_enabled"] is False
            assert (await http.post(url + "/mcp", headers={"Authorization": "Bearer " + team_key})).status_code == 401
            async with streamable_http_client(url + "/mcp", http_client=http) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = (await session.list_tools()).tools
                    assert "submit_work" not in {tool.name for tool in tools}
                    assert not any("userid" in tool.inputSchema.get("properties", {}) or "role" in tool.inputSchema.get("properties", {}) for tool in tools)
                    result = structured(await session.call_tool("search_works", {"query": "山海队"}))
                    assert result["candidates"][0]["id"] == "H-001"
                    assert "members" not in result["candidates"][0]
                    assert (await session.call_tool("get_work", {"work_id": "H-001"})).isError
                    assert (await session.call_tool("search_internal_sop", {"query": "签到"})).isError
                    assert structured(await session.call_tool("search_public_policy", {"query": "怎么提交"}))["sources"] == []
        async with httpx.AsyncClient(headers={"Authorization": "Bearer independent-test-operator-token"}) as http:
            async with streamable_http_client(url + "/mcp", http_client=http) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = structured(await session.call_tool("get_work", {"work_id": "H-001"}))
                    assert result["work"]["members"] == "内部成员甲"
                    assert "key_hash" not in json.dumps(result)
                    assert (await session.call_tool("get_work", {"work_id": "H-002"})).isError
                    assert (await session.call_tool("list_feedback", {})).isError
                    results = structured(await session.call_tool("search_works", {"query": "作品"}))
                    assert all(item["id"] == "H-001" for item in results["candidates"])


async def test_public_search_does_not_use_private_member_fields(bundle):
    _, registry, _, _ = bundle
    registry.register("山海队", "公开作品", "uniqueprivatemember9387")
    queries = QueryService(registry)
    assert not await queries.search_works("uniqueprivatemember9387", StaffIdentity(""))
    assert await queries.search_works("uniqueprivatemember9387", StaffIdentity("operator", "staff"))


def test_staff_credentials_reject_invalid_configuration_and_spoofing():
    with pytest.raises(ValueError):
        StaffAuth('[{"token_sha256":"bad","userid":"staff","role":"admin"}]')
    auth = auth_for()
    with pytest.raises(PermissionError):
        auth.identify("Bearer I am admin")
    assert auth.identify("").role == "public"


@pytest.mark.parametrize("enabled", [False, True])
async def test_ticket_writes_require_explicit_gate_and_verified_credential(bundle, tmp_path, enabled):
    from arena.observability.audit import OperationJournal
    from arena.workflows.tickets import TicketService

    settings, registry, _, _ = bundle
    registry.register("山海队", "公开作品")
    journal = OperationJournal(tmp_path / "journal.sqlite3")
    tickets = TicketService(journal, journal, owner_userid="operator")
    try:
        app = create_staff_app(settings, registry, auth_for(), tickets=tickets, writes_enabled=enabled)
        async with running_server(app) as url:
            async with httpx.AsyncClient(headers={"Authorization": "Bearer independent-test-operator-token"}) as http:
                async with streamable_http_client(url + "/mcp", http_client=http) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        result = await session.call_tool("create_ticket", {"request_id": "incident-1", "summary": "已提交作品找不到版本", "work_id": "H-001"})
                        if not enabled:
                            assert result.isError and not journal.list_tickets()
                            return
                        item = structured(result)
                        ticket_id = item["ticket_id"]
                        assert item["notify_status"] == "queued" and item["assigned_userid"] == "operator"
                        repeat = structured(await session.call_tool("create_ticket", {"request_id": "incident-1", "summary": "已提交作品找不到版本", "work_id": "H-001"}))
                        assert repeat["ticket_id"] == ticket_id and len(journal.list_tickets()) == 1
                        for tool in ("acknowledge_ticket", "start_ticket"):
                            assert not (await session.call_tool(tool, {"ticket_id": ticket_id})).isError
                        assert (await session.call_tool("resolve_ticket", {"ticket_id": ticket_id, "resolution": "已核对", "evidence_urls": []})).isError
                        assert not (await session.call_tool("resolve_ticket", {"ticket_id": ticket_id, "resolution": "已核对 GitHub tag 并补齐登记", "evidence_urls": ["https://example.invalid/commit/proof"]})).isError
                        assert not (await session.call_tool("close_ticket", {"ticket_id": ticket_id})).isError
                        assert journal.get_ticket(ticket_id)["status"] == "closed"
                        assert (await session.call_tool("assign_ticket", {"ticket_id": ticket_id, "assignee_userid": "evil", "reason": "自行提权"})).isError
    finally:
        journal.close()


async def test_admin_proposes_draft_only_from_real_feedback(bundle, tmp_path):
    from arena.observability.audit import OperationJournal
    from arena.workflows.tickets import TicketService

    settings, registry, _, _ = bundle
    registry.feedback({"id": "F-review", "userid": "requester", "role": "participant", "question": "规则不明", "answer": "待人工处理", "tools": [], "escalated": 1})
    journal = OperationJournal(tmp_path / "journal.sqlite3")
    try:
        app = create_staff_app(settings, registry, auth_for(role="admin"), tickets=TicketService(journal, journal), writes_enabled=True)
        async with running_server(app) as url:
            async with httpx.AsyncClient(headers={"Authorization": "Bearer independent-test-operator-token"}) as http:
                async with streamable_http_client(url + "/mcp", http_client=http) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        feedback = structured(await session.call_tool("list_feedback", {}))
                        assert feedback["feedback"][0]["id"] == "F-review"
                        assert "userid" not in feedback["feedback"][0]
                        assert (await session.call_tool("propose_change", {"feedback_id": "F-missing", "summary": "补规则"})).isError
                        draft = structured(await session.call_tool("propose_change", {"feedback_id": "F-review", "summary": "补充规则依据，审核后发布"}))
                        assert draft["status"] == "proposed" and draft["published_at"] is None
                        assert journal.events(draft["proposal_id"])[0]["action"] == "propose_change"
    finally:
        journal.close()


@pytest.mark.parametrize("enabled", [False, True])
async def test_worker_lifecycle_reports_failure_without_readonly_mutation(bundle, tmp_path, enabled):
    from arena.observability.audit import OperationJournal
    from arena.workflows.tickets import TicketService

    class FailedWorker:
        notifier = None
        started = False

        async def run(self):
            self.started = True
            raise RuntimeError("private upstream details must not appear in health")

    settings, registry, _, _ = bundle
    journal = OperationJournal(tmp_path / "journal.sqlite3")
    worker = FailedWorker()
    try:
        app = create_staff_app(settings, registry, tickets=TicketService(journal, journal), writes_enabled=enabled, worker=worker)
        async with running_server(app) as url:
            async with httpx.AsyncClient() as http:
                response = await http.get(url + "/healthz")
                assert worker.started is enabled
                assert response.status_code == (503 if enabled else 200)
                assert "private upstream" not in response.text
                assert response.json()["ticket_worker"]["state"] == ("failed" if enabled else "disabled_read_only")
    finally:
        journal.close()

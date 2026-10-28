"""Explicit live sandbox MCP ticket lifecycle; isolated credentials, no real messages."""

import asyncio
import hashlib
import json
import logging
import os
import secrets
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

import arena  # noqa: F401
from arena.adapters.smartsheet_registry import SmartSheetRegistry
from arena.observability.audit import OperationJournal
from arena.runtime import EnvironmentCredentials
from arena.staff_auth import StaffAuth
from arena.staff_mcp import create_staff_app
from arena.walkthrough import running_server, structured
from arena.wecom_auth import import_user_environment
from arena.workflows.tickets import TicketService


async def main():
    logging.getLogger("mcp").setLevel(logging.CRITICAL)
    import_user_environment(("ARENA_V03_SMARTSHEET_DOCID",))
    docid = os.environ.get("ARENA_V03_SMARTSHEET_DOCID")
    if not docid:
        raise RuntimeError("Run the isolated SmartSheet sandbox acceptance first")
    registry = SmartSheetRegistry(EnvironmentCredentials(), docid=docid, write_enabled=True)
    registry.verify_schema()
    with tempfile.TemporaryDirectory(prefix="arena-cloud-mcp-") as directory:
        journal = OperationJournal(Path(directory) / "operations.sqlite3")
        try:
            principal = "sandbox-owner-b"
            key = secrets.token_urlsafe(32)
            os.environ["ARENA_SANDBOX_STAFF_TOKEN"] = key
            auth = StaffAuth(json.dumps([{"token_sha256": hashlib.sha256(key.encode()).hexdigest(),
                                         "userid": principal, "role": "staff", "work_ids": ["H-001"]}]))
            tickets = TicketService(registry, journal, registry.on_duty, owner_userid=principal)
            app = create_staff_app(registry=registry, auth=auth, tickets=tickets, writes_enabled=True)
            async with running_server(app) as url:
                async with httpx.AsyncClient(headers={"Authorization": "Bearer " + key}, timeout=60) as client:
                    async with streamable_http_client(url + "/mcp", http_client=client) as (read, write, _):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            async def call(name, arguments):
                                result = await session.call_tool(name, arguments)
                                if result.isError:
                                    raise RuntimeError("sandbox_tool_failed:" + name)
                                return structured(result)
                            request = {"request_id": "sandbox-mcp-lifecycle-1", "summary": "虚构MCP工单全流程演练", "work_id": "H-001"}
                            item = await call("create_ticket", request)
                            duplicate = await call("create_ticket", request)
                            assert item["ticket_id"] == duplicate["ticket_id"]
                            identifier = item["ticket_id"]
                            stages = [("assigned", "acknowledge_ticket", {}), ("acknowledged", "start_ticket", {}),
                                      ("in_progress", "resolve_ticket", {"resolution": "虚构演练处理完成，仅验接口流程",
                                        "evidence_urls": ["https://github.com/Eevanes/ABF_demo"]}),
                                      ("resolved", "close_ticket", {})]
                            for status, tool, extra in stages:
                                if item["status"] == status:
                                    item = await call(tool, {"ticket_id": identifier, **extra})
                            assert item["status"] == "closed"
                            readback = registry.get_ticket(identifier)
                            assert readback and readback["status"] == "closed"
                            assert readback["notify_status"] == "queued"
            report = {"mode": "real_smartsheet_localhost_mcp_sandbox", "timestamp": datetime.now(timezone.utc).isoformat(),
                      "ticket_create_retry_deduplicated": True, "ack_start_resolve_close_readback": True,
                      "notify_status": "queued", "messages_sent": 0, "original_demo_modified": False,
                      "workbuddy_identity_passthrough": "not_tested", "credentials": "ephemeral_independent_test_identity"}
            output = Path(__file__).resolve().parents[1] / "docs/v03-cloud-mcp-acceptance.json"
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False))
        finally:
            os.environ.pop("ARENA_SANDBOX_STAFF_TOKEN", None)
            journal.close()


if __name__ == "__main__":
    asyncio.run(main())

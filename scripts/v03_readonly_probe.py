"""Explicit live read-only SmartSheet -> Arena MCP protocol probe. No messages or writes."""

import asyncio
import json

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

import arena  # noqa: F401 -- process-local Windows runtime fallback
from arena.adapters.smartsheet_registry import SmartSheetRegistry
from arena.runtime import EnvironmentCredentials
from arena.staff_mcp import create_staff_app
from arena.walkthrough import running_server, structured


async def main():
    registry = SmartSheetRegistry(EnvironmentCredentials())
    async with running_server(create_staff_app(registry=registry)) as url:
        async with httpx.AsyncClient() as client:
            async with streamable_http_client(url + "/mcp", http_client=client) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = structured(await session.call_tool("search_works", {"query": "山海队"}))
                    denied = await session.call_tool("get_work", {"work_id": "H-001"})
                    assert [work["id"] for work in result["candidates"]] == ["H-001"]
                    assert denied.isError
                    report = {"mode": "live_table_localhost_mcp_read_only", "query_expected_work_matched": True,
                              "anonymous_detail_denied": True, "wecom_messages_sent": 0,
                              "table_writes": 0, "workbuddy_e2e": "not_verified"}
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())

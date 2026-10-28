"""用真实 localhost TCP 和官方 MCP 客户端执行协议演练；明文密钥仅在进程环境中。"""

import asyncio
import json
import logging
import os
import socket
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from arena.config import Settings
from arena.mcp_app import create_app
from arena.store import Store


@asynccontextmanager
async def running_server(app):
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False))
    task = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        async with asyncio.timeout(10):
            while not server.started:
                if task.done():
                    await task
                    raise RuntimeError("MCP server failed to start")
                await asyncio.sleep(0.02)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(task, timeout=5)
        except TimeoutError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        listener.close()


def structured(result) -> dict:
    if result.structuredContent is not None:
        return result.structuredContent
    return json.loads(result.content[0].text)


async def walkthrough(data_dir: Path) -> dict:
    logging.getLogger("mcp").setLevel(logging.CRITICAL)
    settings = Settings(data_dir=data_dir)
    store = Store(data_dir / "registry.sqlite3")
    first, key_a = store.register("协议演练甲", "甲作品")
    second, key_b = store.register("协议演练乙", "乙作品")
    key_a = key_a or store.reset_key(first["id"])
    key_b = key_b or store.reset_key(second["id"])
    os.environ["ARENA_MCP_TEAM_A_KEY"] = key_a
    os.environ["ARENA_MCP_TEAM_B_KEY"] = key_b
    try:
        async with running_server(create_app(settings, store)) as url:
            async with httpx.AsyncClient() as http:
                invalid = await http.post(
                    url + "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
                )
                assert invalid.status_code == 401
                health = (await http.get(url + "/healthz")).json()
            async with httpx.AsyncClient(headers={"Authorization": "Bearer " + key_a}) as http:
                async with streamable_http_client(url + "/mcp", http_client=http) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        tools = await session.list_tools()
                        assert {tool.name for tool in tools.tools} == {
                            "submit_work",
                            "get_my_work",
                            "list_my_versions",
                        }
                        assert all(
                            "work_id" not in tool.inputSchema.get("properties", {}) for tool in tools.tools
                        )
                        mine = structured(await session.call_tool("get_my_work", {}))
                        assert mine["id"] == first["id"]
                        bad = await session.call_tool(
                            "submit_work",
                            {
                                "description": "缺少 README 的协议提交，应当被拒绝。",
                                "files": [{"path": "app.py", "content": "print(1)"}],
                            },
                        )
                        assert bad.isError
                        version = store.require(first["id"])["latest"] + 1
                        good = await session.call_tool(
                            "submit_work",
                            {
                                "description": "真实 MCP 协议提交成功，验证独立队伍身份。",
                                "files": [
                                    {
                                        "path": "README.md",
                                        "content": f"# MCP 真实协议演练 {version}\n" + "运行说明。" * 50,
                                    }
                                ],
                            },
                        )
                        assert not good.isError
                        submitted = structured(good)
                        history = structured(await session.call_tool("list_my_versions", {}))
                        assert history["versions"][-1]["commit_sha"] == submitted["commit_sha"]
            async with httpx.AsyncClient(headers={"Authorization": "Bearer " + key_b}) as http:
                async with streamable_http_client(url + "/mcp", http_client=http) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        other = structured(await session.call_tool("get_my_work", {}))
                        assert other["id"] == second["id"] and other["latest"] == 0
                        other_history = structured(await session.call_tool("list_my_versions", {}))
                        assert not other_history["versions"]
            return {
                "transport": "real localhost TCP + Streamable HTTP + official MCP client",
                "invalid_key_status": invalid.status_code,
                "tools": [tool.name for tool in tools.tools],
                "missing_readme_rejected": bad.isError,
                "submission": submitted,
                "team_isolation_passed": True,
                "health": health,
                "secrets_printed": False,
            }
    finally:
        store.close()

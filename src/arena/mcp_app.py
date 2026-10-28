import asyncio
from contextlib import asynccontextmanager

from mcp.server.fastmcp import Context, FastMCP
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from arena.config import Settings
from arena.store import Store
from arena.submission import InputFile, Submission, SubmissionService
from arena.writer import LocalGitWriter


class MCPAuth:
    def __init__(self, app, store: Store, body_limit: int):
        self.app, self.store, self.body_limit = app, store, body_limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"].rstrip("/") != "/mcp":
            return await self.app(scope, receive, send)
        headers = {k.lower(): v for k, v in scope["headers"]}
        auth = headers.get(b"authorization", b"").decode("latin1")
        key = auth[7:] if auth.startswith("Bearer ") else ""
        if not self.store.authenticate(key):
            return await JSONResponse({"error": "invalid_team_key"}, status_code=401)(scope, receive, send)
        # 完整缓存一个有大小上限的请求体，兼容没有 Content-Length 的分块请求。
        chunks = []
        size = 0
        while True:
            event = await receive()
            if event["type"] == "http.disconnect":
                return
            size += len(event.get("body", b""))
            if size > self.body_limit:
                return await JSONResponse({"error": "request_too_large"}, status_code=413)(
                    scope, receive, send
                )
            chunks.append(event)
            if not event.get("more_body", False):
                break

        async def limited_receive():
            if chunks:
                return chunks.pop(0)
            return await receive()

        await self.app(scope, limited_receive, send)


def create_app(
    settings: Settings | None = None,
    store: Store | None = None,
    with_bot: bool = False,
    with_cloud: bool = False,
    allow_offline: bool = False,
):
    settings = settings or Settings()
    owns_store = store is None
    registry = store or Store(settings.data_dir / "registry.sqlite3")
    service = SubmissionService(settings, registry, LocalGitWriter(settings.data_dir / "works-repo"))
    bot_status: dict = {"state": "not_attached"}
    bridge = None
    if with_cloud:
        from arena.cloud_bridge import CloudBridge

        bridge = CloudBridge(registry)
    mcp = FastMCP(
        "Arena Demo",
        stateless_http=True,
        json_response=True,
        streamable_http_path="/mcp",
        max_request_body_size=settings.max_inline_bytes * 2 + 1024 * 1024,
        instructions="比赛作品提交与查询。本地 demo；作品由服务端根据 Bearer 密钥识别。",
    )

    def identity(ctx: Context) -> tuple[dict, str]:
        request = ctx.request_context.request
        if request is None:
            raise ValueError("仅支持通过已认证 HTTP 请求调用")
        auth = request.headers.get("authorization", "")
        key = auth[7:] if auth.startswith("Bearer ") else ""
        work = registry.authenticate(key)
        if not work:
            raise ValueError("队伍密钥已失效")
        return work, key

    @mcp.tool()
    async def submit_work(
        description: str, files: list[InputFile], ctx: Context, title: str | None = None
    ) -> dict:
        """提交本队新版本。files 为文本或 base64 文件列表，根目录必须有 README.md，
        解码后总大小默认 5MB；不可包含密钥。demo 暂不支持 repo_url。
        description 为 10–2000 字；title 可更新名称。无需提供作品 ID。
        """
        work, key = identity(ctx)
        return await service.submit(
            work["id"], Submission(description=description, files=files, title=title), key
        )

    @mcp.tool()
    async def get_my_work(ctx: Context) -> dict:
        """查询本队固定作品编号、名称、队名、最新版本和截止时间。"""
        work, _ = identity(ctx)
        return {k: work[k] for k in ("id", "title", "team", "latest", "status")} | {
            "deadline": settings.submission_deadline.isoformat(),
            "storage": "local-git",
        }

    @mcp.tool()
    async def list_my_versions(ctx: Context) -> dict:
        """列出本队全部已登记版本、Git tag、commit SHA、检查结果与说明。"""
        work, _ = identity(ctx)
        return {"work_id": work["id"], "versions": registry.versions(work["id"])}

    @asynccontextmanager
    async def lifespan(app):
        tasks = []
        try:
            async with mcp.session_manager.run():
                if with_bot:
                    from arena.bot import run_bot

                    tasks.append(asyncio.create_task(run_bot(settings, registry, bot_status, allow_offline)))
                if bridge:
                    tasks.append(asyncio.create_task(bridge.run()))
                yield
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if owns_store:
                registry.close()

    async def health(request: Request):
        pending = settings.data_dir / "pending_sync.jsonl"
        count = len(pending.read_text(encoding="utf-8").splitlines()) if pending.exists() else 0
        ready = (
            not count
            and (not with_bot or bot_status.get("state") == "authenticated")
            and (not bridge or bridge.status["state"] == "ready")
        )
        return JSONResponse(
            {
                "status": "ok" if ready else "degraded",
                "mode": "wecom-demo" if with_bot or with_cloud else "local-demo",
                "pending_sync": count,
                "storage": "sqlite + local-git",
                "wecom": bot_status if with_bot else "not_attached",
                "smartsheet": bridge.status if bridge else "not_attached",
                "github": "not_attached",
                "deepseek": "not_called_by_mcp",
            },
            status_code=200 if ready else 503,
        )

    inner = mcp.streamable_http_app()
    app = Starlette(routes=[Route("/healthz", health), *inner.routes], lifespan=lifespan)
    app.state.store = registry
    app.state.service = service
    return MCPAuth(app, registry, settings.max_inline_bytes * 2 + 1024 * 1024)

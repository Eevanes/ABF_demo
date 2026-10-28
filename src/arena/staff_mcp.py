"""WorkBuddy-facing deterministic tools, isolated from participant MCP."""

import asyncio
import inspect
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from arena.config import Settings
from arena.services.policy import PolicyService
from arena.services.queries import QueryService, registry_call
from arena.staff_auth import StaffAuth, StaffIdentity
from arena.store import Store


class StaffMCPAuth:
    def __init__(self, app: Any, auth: StaffAuth, body_limit: int = 128 * 1024):
        self.app, self.auth, self.body_limit = app, auth, body_limit
        self.state = app.state

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"].rstrip("/") != "/mcp":
            return await self.app(scope, receive, send)
        headers = {key.lower(): value for key, value in scope["headers"]}
        try:
            self.auth.identify(headers.get(b"authorization", b"").decode("latin1"))
        except PermissionError:
            return await JSONResponse({"error": "invalid_staff_credential"}, status_code=401)(scope, receive, send)
        chunks = []
        size = 0
        while True:
            event = await receive()
            if event["type"] == "http.disconnect":
                return
            size += len(event.get("body", b""))
            if size > self.body_limit:
                return await JSONResponse({"error": "request_too_large"}, status_code=413)(scope, receive, send)
            chunks.append(event)
            if not event.get("more_body", False):
                break

        async def limited_receive():
            return chunks.pop(0) if chunks else await receive()

        await self.app(scope, limited_receive, send)


def create_staff_app(
    settings: Settings | None = None, registry: Any = None, auth: StaffAuth | None = None,
    policy: PolicyService | None = None, tickets: Any = None, writes_enabled: bool | None = None,
    worker: Any = None,
):
    settings = settings or Settings()
    owns_registry = registry is None
    registry = registry if registry is not None else Store(settings.data_dir / "registry.sqlite3")
    auth = auth or StaffAuth()
    policy = policy or PolicyService(Path(__file__).parent / "knowledge")
    queries = QueryService(registry)
    writes = writes_enabled if writes_enabled is not None else os.environ.get("ARENA_STAFF_WRITES_ENABLED") == "true"
    worker_status = {"state": "not_attached" if worker is None else "disabled_read_only"}
    mcp = FastMCP(
        "Arena Staff", stateless_http=True, json_response=True, streamable_http_path="/mcp",
        max_request_body_size=128 * 1024,
        instructions="公共查询不证明员工身份；独立员工凭据不证明企微发送者已透传。不得猜测规则、作品或通知状态。",
    )

    def identity(ctx: Context) -> StaffIdentity:
        request = ctx.request_context.request
        if request is None:
            raise PermissionError("仅支持带服务端认证上下文的 HTTP 请求")
        return auth.identify(request.headers.get("authorization", ""))

    @mcp.tool()
    async def search_works(query: str, ctx: Context) -> dict:
        """查询可见作品；多个候选时请用户确认。"""
        results = await queries.search_works(query, identity(ctx))
        certain = bool(results) and results[0]["score"] >= 85 and (
            len(results) == 1 or results[0]["score"] - results[1]["score"] >= 15
        )
        return {"candidates": results, "requires_confirmation": bool(results) and not certain}

    @mcp.tool()
    async def get_work(work_id: str, ctx: Context) -> dict:
        """独立认证工作人员查询授权范围内作品详情。"""
        return {"work": await queries.get_work(work_id, identity(ctx))}

    @mcp.tool()
    async def list_all_versions(work_id: str, ctx: Context) -> dict:
        """独立认证工作人员查询授权范围内作品的版本与证据。"""
        return {"work_id": work_id, "versions": await queries.list_versions(work_id, identity(ctx))}

    @mcp.tool()
    async def search_public_policy(query: str, ctx: Context) -> dict:
        """只返回已审批发布且生效的公开规则；空结果表示无已发布依据。"""
        return {"sources": policy.search(query, identity(ctx)), "snapshot_at": policy.snapshot_at.isoformat()}

    @mcp.tool()
    async def search_internal_sop(query: str, ctx: Context) -> dict:
        """独立认证工作人员检索已发布内部 SOP。"""
        return {"sources": policy.search(query, identity(ctx), internal=True), "snapshot_at": policy.snapshot_at.isoformat()}

    @mcp.tool()
    async def get_on_duty(category: str, ctx: Context) -> dict:
        """独立认证工作人员查询当班负责人；无当班不构造责任人。"""
        return {"duty": await queries.get_on_duty(category, identity(ctx))}

    @mcp.tool()
    async def list_feedback(ctx: Context) -> dict:
        """仅 Owner/Admin 审查差评与升级反馈，不向普通工作人员开放提问人数据。"""
        principal = identity(ctx)
        principal.require_staff()
        if principal.role != "admin":
            raise PermissionError("反馈审查须管理员身份")
        rows = await registry_call(registry, "feedback_report")
        return {"feedback": [{key: row[key] for key in (
            "id", "feedback_id", "time", "role", "question", "answer", "tools", "escalated",
            "assignee", "rating", "ticket_id", "skill_version", "policy_version", "improvement_issue_id"
        ) if key in row} for row in rows]}

    if tickets is not None:
        async def ticket_call(method: str, ctx: Context, *args, write: bool = False, **kwargs):
            from arena.workflows.tickets import Actor

            principal = identity(ctx)
            principal.require_staff()
            if write and not writes:
                raise PermissionError("工作人员写操作尚未启用；须先验收独立认证和会话隔离")
            operation = getattr(tickets, method)
            actor = Actor(principal.userid, principal.role)
            if inspect.iscoroutinefunction(operation):
                return await operation(actor, *args, **kwargs)
            value = await asyncio.to_thread(operation, actor, *args, **kwargs)
            return await value if inspect.isawaitable(value) else value

        @mcp.tool()
        async def create_ticket(
            request_id: str, summary: str, ctx: Context, category: str = "其他",
            work_id: str | None = None, evidence_urls: list[str] | None = None, priority: str = "normal",
        ) -> dict:
            """创建幂等工单；记录创建不代表通知已投递。"""
            identity(ctx).require_staff(work_id)
            return await ticket_call(
                "create", ctx, request_id, summary, category=category, work_id=work_id,
                evidence_urls=evidence_urls, priority=priority, write=True,
            )

        @mcp.tool()
        async def get_my_tickets(ctx: Context) -> dict:
            """读取当前独立认证身份可见且在授权作品范围内的工单。"""
            rows = await ticket_call("list", ctx)
            principal = identity(ctx)
            return {"tickets": [row for row in rows if principal.work_ids is None or not row.get("work_id") or row["work_id"] in principal.work_ids]}

        @mcp.tool()
        async def list_tickets(ctx: Context) -> dict:
            """审查当前身份可见工单；Owner/Admin 可用于反馈 triage。"""
            return await get_my_tickets(ctx)

        @mcp.tool()
        async def propose_change(feedback_id: str, summary: str, ctx: Context, issue_url: str | None = None) -> dict:
            """Owner/Admin 针对真实待审反馈保存改进草案；不会发布规则或创建远端 Issue。"""
            rows = (await list_feedback(ctx))["feedback"]
            if not any(row.get("feedback_id", row.get("id")) == feedback_id for row in rows):
                raise ValueError("找不到对应待审反馈")
            return await ticket_call("propose_change", ctx, feedback_id, summary, issue_url=issue_url, write=True)

        @mcp.tool()
        async def get_ticket(ticket_id: str, ctx: Context) -> dict:
            """读取本人发起或本人负责的工单。"""
            item = await ticket_call("get", ctx, ticket_id)
            identity(ctx).require_staff(item.get("work_id"))
            return item

        async def transition_ticket(ticket_id: str, status: str, ctx: Context, **kwargs) -> dict:
            item = await ticket_call("get", ctx, ticket_id)
            identity(ctx).require_staff(item.get("work_id"))
            return await ticket_call("transition", ctx, ticket_id, status, write=True, **kwargs)

        @mcp.tool()
        async def acknowledge_ticket(ticket_id: str, ctx: Context) -> dict:
            """由工单授权负责人确认接单。"""
            return await transition_ticket(ticket_id, "acknowledged", ctx)

        @mcp.tool()
        async def start_ticket(ticket_id: str, ctx: Context) -> dict:
            """负责人开始处理已确认的工单。"""
            return await transition_ticket(ticket_id, "in_progress", ctx)

        @mcp.tool()
        async def resolve_ticket(ticket_id: str, resolution: str, evidence_urls: list[str], ctx: Context) -> dict:
            """负责人附处理说明与证据后解决工单。"""
            return await transition_ticket(ticket_id, "resolved", ctx, resolution=resolution, evidence_urls=evidence_urls)

        @mcp.tool()
        async def close_ticket(ticket_id: str, ctx: Context) -> dict:
            """工单请求人或管理员确认结案。"""
            return await transition_ticket(ticket_id, "closed", ctx)

        @mcp.tool()
        async def assign_ticket(ticket_id: str, assignee_userid: str, reason: str, ctx: Context) -> dict:
            """仅管理员可以附原因人工改派工单，不能更改操作者身份。"""
            principal = identity(ctx)
            if principal.role != "admin":
                raise PermissionError("人工改派须管理员身份")
            item = await ticket_call("get", ctx, ticket_id)
            principal.require_staff(item.get("work_id"))
            return await ticket_call("assign", ctx, ticket_id, assignee_userid, reason, write=True)

    @asynccontextmanager
    async def lifespan(app):
        task = None

        async def run_worker():
            worker_status["state"] = "running"
            try:
                await worker.run()
                worker_status["state"] = "stopped"
            except asyncio.CancelledError:
                worker_status["state"] = "stopped"
                raise
            except Exception as exc:
                # Provider exceptions may contain private request details.
                worker_status.update(state="failed", error=type(exc).__name__)

        try:
            async with mcp.session_manager.run():
                if worker is not None and writes and tickets is not None:
                    task = asyncio.create_task(run_worker())
                yield
        finally:
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            if owns_registry:
                registry.close()

    async def health(request: Request):
        ready = worker_status["state"] not in ("failed", "stopped")
        return JSONResponse({
            "status": "ok" if ready else "degraded", "scope": "staff-mcp-only",
            "mode": "staff-mcp", "identity_mode": "independent-token-proxy",
            "wecom_sender_verified": False, "writes_enabled": bool(tickets is not None and writes),
            "policy_snapshot_at": policy.snapshot_at.isoformat(), "policy_drafts_excluded": policy.draft_count,
            "workbuddy_e2e": "not_verified", "ticket_worker": worker_status,
            "notification_provider_attached": worker is not None and getattr(worker, "notifier", None) is not None,
        }, status_code=200 if ready else 503)

    inner = mcp.streamable_http_app()
    app = Starlette(routes=[Route("/healthz", health), *inner.routes], lifespan=lifespan)
    app.state.queries, app.state.policy, app.state.mcp = queries, policy, mcp
    return StaffMCPAuth(app, auth)

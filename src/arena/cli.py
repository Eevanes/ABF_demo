import asyncio
import csv
import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import cast

import typer
import uvicorn

from arena.config import Settings
from arena.harness import Harness, LocalMessenger
from arena.store import Store
from arena.submission import InputFile, Submission, SubmissionService
from arena.writer import LocalGitWriter

app = typer.Typer(no_args_is_help=True)


@app.callback()
def import_local_configuration():
    from arena.wecom_auth import import_user_environment

    import_user_environment(
        (
            "WECOM_BOT_ID",
            "WECOM_BOT_SECRET",
            "WECOM_CLI_ACCESS_TOKEN",
            "DEEPSEEK_API_KEY",
            "LLM_API_KEY",
            "LLM_MODEL",
            "LLM_BASE_URL",
            "SMARTSHEET_DOCID",
            "SMARTSHEET_URL",
            "SHEET_WORKS",
            "SHEET_VERSIONS",
            "SHEET_DUTY",
            "SHEET_FEEDBACK",
            "STAFF_USERIDS",
            "ADMIN_USERIDS",
            "ARENA_REGISTRY", "ARENA_WRITER", "ARENA_TEAM_CREDENTIALS",
            "ARENA_STAFF_CREDENTIALS", "ARENA_STAFF_WRITES_ENABLED", "ARENA_SMARTSHEET_WRITES_ENABLED",
            "GITHUB_APP_ID", "GITHUB_APP_PRIVATE_KEY", "GITHUB_INSTALLATION_ID", "GITHUB_REPO",
            "GITHUB_BRANCH", "PUBLIC_BASE_URL", "SHEET_TICKETS",
            "ARENA_V04_SMARTSHEET_DOCID", "ARENA_POLICY_RELEASE",
        )
    )


@app.command()
def connect_model(port: int = 18767):
    """用户在本机页面输入 DeepSeek key，并验证真实 tool call；只保存环境变量。"""
    from arena.model_setup import create_model_app

    typer.echo(f"请在 http://127.0.0.1:{port} 输入 DeepSeek API Key，勿发到聊天。")
    uvicorn.run(create_model_app(), host="127.0.0.1", port=port, log_level="critical", access_log=False)


@app.command()
def provision_wecom():
    """创建比赛专用四表，读回字段并保存本机环境配置；不修改已有记录。"""
    from arena.wecom_cli import provision

    emit(provision())


@app.command()
def connect_wecom(port: int = 18766):
    """官方扫码协议接入，仅写入 Windows 用户环境变量；不用 CLI 凭据文件。"""
    from arena.wecom_auth import create_auth_app

    typer.echo(f"请打开 http://127.0.0.1:{port} 并用企业微信扫码。凭据仅保存为本机用户环境变量。")
    uvicorn.run(create_auth_app(), host="127.0.0.1", port=port, log_level="critical", access_log=False)


def emit(value):
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2))


@app.command()
def serve(
    host: str = "127.0.0.1",
    port: int = 8765,
    with_bot: bool = False,
    with_cloud: bool = False,
    allow_offline: bool = False,
):
    """启动本地 MCP 服务；绑定本机，不进行云端写入。"""
    from arena.mcp_app import create_app

    uvicorn.run(
        create_app(with_bot=with_bot, with_cloud=with_cloud, allow_offline=allow_offline),
        host=host,
        port=port,
        log_level="warning",
        access_log=False,
    )


@app.command()
def serve_staff(host: str = "127.0.0.1", port: int = 8766):
    """WorkBuddy staff MCP; public read-only until independent trusted authentication is configured."""
    from arena.runtime import registry_backend
    from arena.staff_mcp import create_staff_app

    settings = Settings()
    registry = registry_backend(settings)
    from arena.observability.audit import OperationJournal
    from arena.workflows.outbox import NotificationOutbox
    from arena.workflows.runner import TicketWorker
    from arena.workflows.tickets import TicketBackend, TicketService

    journal = OperationJournal(settings.data_dir / "workflow-operations.sqlite3")
    ticket_backend = cast(TicketBackend, registry) if hasattr(registry, "save_ticket") else journal
    tickets = TicketService(ticket_backend, journal, registry.on_duty,
                            settings.admin_userids.split(",")[0])
    worker = TicketWorker(tickets, NotificationOutbox(journal)) if os.environ.get("ARENA_STAFF_WRITES_ENABLED", "").lower() == "true" else None
    try:
        uvicorn.run(create_staff_app(settings, registry, tickets=tickets, worker=worker), host=host, port=port,
                    log_level="warning", access_log=False)
    finally:
        journal.close()
        registry.close()


@app.command()
def reconcile():
    """Recover pending registration from immutable Git evidence without creating new versions."""
    from arena.runtime import backends

    settings = Settings()
    registry, writer = backends(settings)
    try:
        result = asyncio.run(SubmissionService(settings, registry, writer).reconcile())
        emit(result)
        if result["pending"]:
            raise typer.Exit(1)
    finally:
        registry.close()


@app.command()
def doctor_v03(live_read: bool = False):
    """Read-only v0.3 readiness report; never sends messages, writes tables or creates tokens."""
    from arena.runtime import EnvironmentCredentials

    required = ("GITHUB_APP_ID", "GITHUB_APP_PRIVATE_KEY", "GITHUB_INSTALLATION_ID", "GITHUB_REPO", "PUBLIC_BASE_URL")
    report: dict = {
        "mode": "live_read_only" if live_read else "configuration_only",
        "configured": {key: bool(os.environ.get(key)) for key in required},
        "workbuddy_identity_passthrough": "not_verified",
        "workbuddy_channel_e2e": "not_verified",
        "github_app_e2e": "not_verified",
        "production_cutover": False,
    }
    if live_read:
        from arena.adapters.smartsheet_registry import SmartSheetRegistry

        try:
            registry = SmartSheetRegistry(EnvironmentCredentials())
            works = registry.works()
            report["smartsheet"] = {"state": "live_read_passed", "works_count": len(works)}
            from arena.services.queries import QueryService
            from arena.staff_auth import StaffIdentity

            # Real test-table query, no personal or credential fields in the report.
            result = asyncio.run(QueryService(registry).search_works("山海队", StaffIdentity("")))
            report["smartsheet"]["query_result_count"] = len(result)
        except Exception as exc:
            report["smartsheet"] = {"state": "failed", "error_type": type(exc).__name__}
    emit(report)


@app.command()
def doctor_v04(live_read: bool = False):
    """v0.4 配置检查；--live-read 仅只读独立 v0.4 沙盒，不写表、不发消息。"""
    from arena.readiness import report_json

    typer.echo(report_json(live_read))


@app.command()
def import_teams(path: Path):
    """导入 CSV（队名、作品名、成员），幂等；新密钥仅写入当前进程环境。"""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if any(not row.get("队名", "").strip() for row in rows):
        raise typer.BadParameter("CSV 必须有非空队名")
    settings = Settings()
    store = Store(settings.data_dir / "registry.sqlite3")
    try:
        for row in rows:
            work, key = store.register(row["队名"].strip(), row.get("作品名", ""), row.get("成员", ""))
            if key:
                os.environ[f"ARENA_TEAM_{work['id'].replace('-', '_')}_KEY"] = key
            emit(
                {
                    "id": work["id"],
                    "team": work["team"],
                    "created": key is not None,
                    "note": "demo 不输出明文；独立 CLI 进程退出后需通过 serve-demo 的进程内会话演练",
                }
            )
    finally:
        store.close()


@app.command()
def bind_key(work_id: str, env_name: str = "ARENA_TEAM_KEY"):
    """将本机环境变量中的密钥绑定到作品；不打印或保存密钥明文。"""
    key = os.environ.get(env_name, "")
    if not key:
        raise typer.BadParameter("指定环境变量为空")
    store = Store(Settings().data_dir / "registry.sqlite3")
    try:
        store.bind_key(work_id, key)
        emit({"id": work_id, "bound": True, "env_name": env_name})
    finally:
        store.close()


@app.command()
def ask(question: str, userid: str = "demo-participant", llm: bool = False):
    """本地演练查询；--llm 才会调用 DeepSeek。"""
    settings = Settings()
    store = Store(settings.data_dir / "registry.sqlite3")
    try:
        emit(asyncio.run(Harness(settings, store).ask(question, userid, use_llm=llm)))
    finally:
        store.close()


@app.command()
def feedback_report():
    """查看点踩与升级问题；不发送消息。"""
    store = Store(Settings().data_dir / "registry.sqlite3")
    try:
        emit(store.feedback_report())
    finally:
        store.close()


@app.command()
def rate(feedback_id: str, userid: str, rating: str):
    store = Store(Settings().data_dir / "registry.sqlite3")
    try:
        store.rate(feedback_id, userid, rating)
        emit({"updated": True})
    finally:
        store.close()


@app.command()
def bot():
    """配置环境变量后单独运行企业微信机器人；尚待现场联调。"""
    from arena.bot import run_bot

    settings = Settings()
    store = Store(settings.data_dir / "registry.sqlite3")
    try:
        asyncio.run(run_bot(settings, store))
    finally:
        store.close()


def command_probe(args: list[str]) -> dict:
    try:
        command = shutil.which(args[0])
        if not command:
            return {"ok": False, "state": "not_installed"}
        result = subprocess.run(
            [command, *args[1:]],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        try:
            body = json.loads(result.stdout)
        except ValueError:
            body = None
        if isinstance(body, dict) and "error" in body:
            return {"ok": False, "state": "api_error", "code": body["error"].get("code")}
        return {
            "ok": result.returncode == 0,
            "state": "command_completed" if result.returncode == 0 else "command_failed",
        }
    except (OSError, subprocess.TimeoutExpired):
        return {"ok": False, "state": "probe_failed_or_timeout"}


@app.command()
def selftest():
    """只读环境探针，不发消息、不创建表格、不写 GitHub、不调用付费模型。"""
    settings = Settings()
    variables = [
        "WECOM_CORP_ID",
        "WECOM_APP_SECRET",
        "WECOM_BOT_ID",
        "WECOM_BOT_SECRET",
        "SMARTSHEET_DOCID",
        "SHEET_WORKS",
        "SHEET_VERSIONS",
        "SHEET_DUTY",
        "SHEET_FEEDBACK",
        "GITHUB_APP_ID",
        "GITHUB_APP_PRIVATE_KEY",
        "GITHUB_INSTALLATION_ID",
        "GITHUB_REPO",
        "PUBLIC_BASE_URL",
    ]
    emit(
        {
            "probe_mode": "read_only",
            "wecom_identity": command_probe(["wecom-cli", "identity", "whoami"]),
            "github_cli": command_probe(["gh", "api", "user", "--jq", ".login"]),
            "docker_engine": command_probe(["docker", "info", "--format", "{{.ServerVersion}}"]),
            "deepseek_configured": bool(settings.llm_api_key.get_secret_value()),
            "deepseek_live_test": "not_run",
            "environment_presence": {name: bool(os.environ.get(name)) for name in variables},
        }
    )


async def demo_flow(settings: Settings) -> dict:
    store = Store(settings.data_dir / "registry.sqlite3")
    messenger = LocalMessenger()
    try:
        work, key = store.register("山海队", "RAG 知识助手", "演练选手甲")
        if not key:
            key = store.reset_key(work["id"])
        os.environ["ARENA_DEMO_TEAM_KEY"] = key
        other, _ = store.register("星火队", "无障碍阅读", "演练选手乙")
        store.register("向善队", "公益地图", "演练选手丙")
        current = datetime.now(timezone.utc)
        store.add_duty(
            (current - timedelta(hours=1)).isoformat(),
            (current + timedelta(hours=8)).isoformat(),
            "其他",
            "演练负责人",
            "demo-owner",
        )
        writer = LocalGitWriter(settings.data_dir / "works-repo")
        service = SubmissionService(settings, store, writer)
        sequence = store.require(work["id"])["latest"]
        first = await service.submit(
            work["id"],
            Submission(
                description="第一版：提供 RAG 问答与运行说明。",
                files=[
                    InputFile(
                        path="README.md", content="# RAG 演练\n" + "这是用于本地演练的作品与运行说明。" * 20
                    ),
                    InputFile(path="src/old.py", content=f"print('old-{sequence}')"),
                ],
            ),
            key,
        )
        second = await service.submit(
            work["id"],
            Submission(
                description="第二版：移除旧脚本并更新说明。",
                files=[
                    InputFile(
                        path="README.md",
                        content="# RAG 演练第二版\n" + "这是用于本地演练的作品与运行说明。" * 20,
                    ),
                    InputFile(path="src/main.py", content=f"print('new-{sequence}')"),
                ],
            ),
            key,
        )
        try:
            await service.submit(
                work["id"],
                Submission(
                    description="这一版没有 README，应当被拒绝。",
                    files=[InputFile(path="main.py", content="print(1)")],
                ),
                key,
            )
        except ValueError as exc:
            rejected = str(exc)
        else:
            raise AssertionError("缺少 README 未被拦截")
        harness = Harness(settings, store, messenger)
        query = await harness.ask("山海队的作品ID", "demo-participant")
        rules = await harness.ask("怎么提交", "demo-participant")
        escalation = await harness.ask("太阳风暴后临时改变奖金额度谁裁决", "demo-participant")
        store.rate(escalation["feedback_id"], "demo-participant", "踩")
        return {
            "mode": "local-demo",
            "teams": len(store.works()),
            "versions": [first, second],
            "rejected_submission": rejected,
            "old_file_removed": not (writer.root / "works" / work["id"] / "src" / "old.py").exists(),
            "other_team_untouched": store.require(other["id"])["latest"] == 0,
            "work_query": query,
            "rules_query": rules,
            "escalation": escalation,
            "feedback_items": len(store.feedback_report()),
            "real_notifications_sent": 0,
            "secrets_printed": False,
            "data_dir": str(settings.data_dir.resolve()),
        }
    finally:
        store.close()


@app.command()
def demo():
    """演练三队报名、两版提交、拒收、查询、规则答疑与转人工记录。"""
    emit(asyncio.run(demo_flow(Settings())))


@app.command()
def serve_demo(port: int = 8765):
    """进程内生成队伍密钥并启动 MCP；不在控制台输出或持久化明文密钥。"""
    from arena.mcp_app import create_app

    settings = Settings()
    store = Store(settings.data_dir / "registry.sqlite3")
    work, key = store.register("MCP 演练队", "MCP 演练作品")
    key = key or store.reset_key(work["id"])
    os.environ["ARENA_DEMO_TEAM_KEY"] = key
    typer.echo("MCP 已启动。密钥仅存在本服务进程环境；使用 scripts/mcp_walkthrough.py 演练真实协议。")
    try:
        uvicorn.run(
            create_app(settings, store), host="127.0.0.1", port=port, log_level="warning", access_log=False
        )
    finally:
        store.close()


if __name__ == "__main__":
    app()

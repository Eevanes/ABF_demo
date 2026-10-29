"""Two-team/two-version real MCP -> GitHub App -> isolated SmartSheet rehearsal.

Default: configuration-only, no network and no writes. --execute creates synthetic
records in a dedicated v0.4 sandbox and real artifacts in GITHUB_REPO. Never run
against the code repository. Raw credentials exist only in process environment.
Failed runs retain their journal and safe evidence for explicit reconciliation.
"""

import argparse
import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

import arena  # noqa: F401 -- Windows WMI workaround before dependencies
from arena.adapters.github_app_writer import GitHubAppWriter
from arena.adapters.smartsheet_registry import SCHEMA, SmartSheetRegistry
from arena.config import Settings
from arena.mcp_app import create_app
from arena.readiness import GITHUB_VARIABLES, configuration_report
from arena.runtime import EnvironmentCredentials
from arena.walkthrough import running_server, structured
from arena.wecom_auth import import_user_environment
from arena.wecom_cli import WecomCLI


class AcceptanceError(RuntimeError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise AcceptanceError(code)


def failure_code(exc: BaseException) -> str:
    if isinstance(exc, AcceptanceError):
        return str(exc)
    # MCP context managers wrap errors in task groups; keep our own safe codes.
    if isinstance(exc, BaseExceptionGroup):
        for child in exc.exceptions:
            code = failure_code(child)
            if code != "external_check_failed":
                return code
    return "external_check_failed"


class RegistrationFailure:
    """Hold only this rehearsal's registry write until explicit reconciliation."""

    def __init__(self, registry: Any):
        self.registry, self.armed = registry, False

    def __getattr__(self, name: str):
        return getattr(self.registry, name)

    def record_submission(self, *args):
        if self.armed:
            raise RuntimeError("acceptance_injected_registration_failure")
        return self.registry.record_submission(*args)


async def invoke(session: ClientSession, tool: str, arguments: dict) -> dict:
    result = await session.call_tool(tool, arguments)
    require(not result.isError, "mcp_" + tool + "_failed")
    return structured(result)


def request_payload(run_id: str, work_id: str, version: int) -> dict:
    return {
        "submission_id": f"v04-{run_id}-{work_id}-{version}",
        "description": f"v0.4 隔离验收虚构作品第 {version} 版；不作为真实参赛作品。",
        "files": [
            {"path": "README.md", "content": f"# Demo {work_id} v{version}\n" +
                "这是隔离验收数据，仅用于验证 MCP、GitHub 与台账一致性。运行：python src/main.py。\n" * 8},
            {"path": "src/old.py" if version == 1 else "src/main.py",
             "content": f"print('Arena Demo {run_id} {work_id} v{version}')\n"},
        ],
    }


async def verify_artifact(writer: GitHubAppWriter, item: dict, payload: dict) -> None:
    ref = await writer.ref("tags/" + item["tag"])
    require(ref is not None and ref["object"]["sha"] == item["commit_sha"], "tag_sha_mismatch")
    meta = await writer.metadata(item["work_id"], item["commit_sha"])
    require(meta is not None and meta.get("submission_id") == item["submission_id"]
        and meta.get("version") == item["version"], "github_metadata_mismatch")
    for file in payload["files"]:
        value = await writer.request("GET", writer.prefix + "/contents/works/" + item["work_id"] +
            "/" + file["path"] + "?ref=" + quote(item["commit_sha"], safe=""))
        require(value is not None and base64.b64decode(value["content"]) == file["content"].encode(),
            "github_file_mismatch")
    if item["version"] == 2:
        deleted = await writer.request("GET", writer.prefix + "/contents/works/" + item["work_id"] +
            "/src/old.py?ref=" + quote(item["commit_sha"], safe=""), missing=True)
        require(deleted is None, "deleted_file_remains")
        comparison = await writer.request("GET", writer.prefix + "/compare/" +
            quote(f"{item['work_id']}/v1", safe="") + "..." + quote(item["tag"], safe=""))
        old_path = f"works/{item['work_id']}/src/old.py"
        require(comparison is not None and any(
            (row.get("filename") == old_path and row.get("status") == "removed")
            or (row.get("previous_filename") == old_path and row.get("status") == "renamed")
            for row in comparison.get("files", [])), "version_diff_missing")


async def exercise(settings: Settings, registry: Any, writer: Any, teams: dict[str, str],
                   run_id: str, verify_files=verify_artifact) -> dict:
    """Real localhost MCP clients; injected registry outage is reported explicitly."""
    proxy = RegistrationFailure(registry)
    app = create_app(settings, proxy, writer=writer)
    submissions = []
    checks = {}
    async with running_server(app) as url:
        async with httpx.AsyncClient() as http:
            unauthorized = await http.post(url + "/mcp", headers={"Authorization": "Bearer invalid-v04-key"})
            require(unauthorized.status_code == 401, "invalid_key_not_rejected")
            checks["invalid_key_rejected"] = True
        for team_index, (work_id, key) in enumerate(teams.items()):
            async with httpx.AsyncClient(headers={"Authorization": "Bearer " + key}, timeout=120) as http:
                async with streamable_http_client(url + "/mcp", http_client=http) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        tools = (await session.list_tools()).tools
                        require({tool.name for tool in tools} == {
                            "submit_work", "get_my_work", "list_my_versions"}, "participant_tool_contract_changed")
                        require(all("work_id" not in tool.inputSchema.get("properties", {}) for tool in tools),
                            "participant_can_choose_another_work")
                        mine = await invoke(session, "get_my_work", {})
                        require(mine["id"] == work_id and mine["latest"] == 0, "team_identity_or_initial_version")
                        team_versions = []
                        for version in (1, 2):
                            payload = request_payload(run_id, work_id, version)
                            if team_index == 1 and version == 1:
                                proxy.armed = True
                                failed = await session.call_tool("submit_work", payload)
                                require(failed.isError and len(app.app.state.service.journal.pending()) == 1,
                                    "registry_failure_not_observed")
                                evidence = await writer.recover(work_id, version)
                                require(evidence is not None, "git_not_written_before_failure")
                                proxy.armed = False
                                recovered = await app.app.state.service.reconcile()
                                require(not recovered["pending"] and payload["submission_id"] in recovered["reconciled"],
                                    "reconcile_failed")
                                checks["registry_failure_reconciled_without_upload"] = True
                            item = await invoke(session, "submit_work", payload)
                            require(item["work_id"] == work_id and item["version"] == version, "version_mismatch")
                            require(await invoke(session, "submit_work", payload) == item, "idempotent_retry_mismatch")
                            await verify_files(writer, item, payload)
                            if team_index == 1 and version == 1:
                                require(item["commit_sha"] == evidence["commit_sha"], "reconcile_reuploaded")
                            team_versions.append(item)
                            submissions.append(item)
                        history = await invoke(session, "list_my_versions", {})
                        require(history["work_id"] == work_id and len(history["versions"]) == 2, "team_history_mismatch")
                        for row, item in zip(history["versions"], team_versions):
                            require(all(row[k] == item[k] for k in ("version", "tag", "commit_sha", "submission_id")),
                                "ledger_mismatch")
                        require((await invoke(session, "get_my_work", {}))["latest"] == 2, "latest_pointer_mismatch")
                        changed = request_payload(run_id, work_id, 2) | {"description": "同一个提交编号更改说明必须被拒绝。"}
                        require((await session.call_tool("submit_work", changed)).isError, "changed_request_id_accepted")
                        unchanged = request_payload(run_id, work_id, 2)
                        unchanged["submission_id"] += "-unchanged"
                        require((await session.call_tool("submit_work", unchanged)).isError, "unchanged_files_accepted")
                        malicious = request_payload(run_id, work_id, 3)
                        malicious["files"].append({"path": "../escape.py", "content": "pass"})
                        require((await session.call_tool("submit_work", malicious)).isError, "malicious_path_accepted")
                        original_deadline = settings.submission_deadline
                        try:
                            settings.submission_deadline = datetime.now(timezone.utc) - timedelta(seconds=1)
                            require((await session.call_tool("submit_work", request_payload(run_id, work_id, 3))).isError,
                                "expired_request_accepted")
                        finally:
                            settings.submission_deadline = original_deadline
                        require(len((await invoke(session, "list_my_versions", {}))["versions"]) == 2,
                            "rejected_request_created_version")
        checks.update(two_teams_two_versions=True, idempotent_retry=True, team_isolation=True,
            changed_request_id_rejected=True, unchanged_files_rejected=True,
            malicious_path_rejected=True, expired_request_rejected=True)
    return {"mode": "real_github_smartsheet_mcp", "run_id": run_id,
        "transport": "localhost TCP + official MCP client", "checks": checks,
        "submissions": submissions, "remote_https": "not_verified", "real_notifications_sent": 0,
        "registry_fault": "injected_locally_after_real_github_write", "production_cutover": False}


async def execute(run_id: str, data_dir: Path) -> dict:
    require(not data_dir.exists(), "run_directory_exists_use_reconcile_not_new_credentials")
    require(all(os.environ.get(name) for name in GITHUB_VARIABLES), "github_app_configuration_required")
    require(os.environ["GITHUB_REPO"].lower() != "eevanes/abf_demo", "dedicated_artifact_repo_required")
    writer = GitHubAppWriter.from_environment()
    require(await writer.ref("heads/" + writer.branch) is not None, "initialized_github_branch_required")
    cli = WecomCLI()
    docid = os.environ.get("ARENA_V04_SMARTSHEET_DOCID", "")
    if not docid:
        created = cli.call("smartsheet", "create", payload={
            "name": f"ABF · Arena v0.4 隔离验收 {run_id}", "sheet_title": "作品", "fields": SCHEMA["作品"]})
        docid = created.get("docid", "")
        require(bool(docid), "sandbox_create_receipt_missing")
        # Save immediately so interruption cannot lose the newly created sandbox.
        if os.name == "nt":
            import winreg
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Environment") as registry_key:
                winreg.SetValueEx(registry_key, "ARENA_V04_SMARTSHEET_DOCID", 0, winreg.REG_SZ, docid)
        os.environ["ARENA_V04_SMARTSHEET_DOCID"] = docid
        for title, fields in SCHEMA.items():
            if title != "作品":
                cli.call("smartsheet", "sheets", "add", payload={
                    "docid": docid, "sheet_title": title, "type": "add", "fields": fields})
    require(docid != os.environ.get("SMARTSHEET_DOCID"), "sandbox_cannot_be_operational_table")
    registry = SmartSheetRegistry(EnvironmentCredentials(), cli, docid, write_enabled=True)
    registry.verify_schema()
    data_dir.mkdir(parents=True)
    teams = {}
    for index in (1, 2):
        work_id = f"H-{int(uuid.uuid4().hex[:10], 16)}"
        require(registry.get(work_id) is None, "sandbox_work_id_collision")
        # A read-only check: recover() can create a missing tag and is inappropriate here.
        namespace = await writer.request("GET", writer.prefix + f"/contents/works/{work_id}?ref=" +
            quote(writer.branch, safe=""), missing=True)
        require(namespace is None, "artifact_work_id_collision")
        teams[work_id] = secrets.token_urlsafe(32)
        cli.call("smartsheet", "records", "add", payload={"docid": docid, "sheet_title": "作品",
            "key_type": "field_title", "records": [{"values": {"作品ID": work_id,
            "队名": f"v04-{run_id}-虚构队{index}", "作品名": "v0.4 隔离验收作品",
            "最新版本": 0, "状态": "已报名"}}]})
    previous = os.environ.get("ARENA_TEAM_CREDENTIALS")
    ephemeral_names = []
    for work_id, key in teams.items():
        env_name = f"ARENA_V04_{run_id}_{work_id}_TEAM_KEY"
        os.environ[env_name] = key
        ephemeral_names.append(env_name)
    os.environ["ARENA_TEAM_CREDENTIALS"] = json.dumps({
        work_id: hashlib.sha256(key.encode()).hexdigest() for work_id, key in teams.items()})
    try:
        settings = Settings(data_dir=data_dir, submission_deadline=datetime.now(timezone.utc) + timedelta(days=1))
        return await exercise(settings, registry, writer, teams, run_id)
    finally:
        registry.close()
        for env_name in ephemeral_names:
            os.environ.pop(env_name, None)
        if previous is None:
            os.environ.pop("ARENA_TEAM_CREDENTIALS", None)
        else:
            os.environ["ARENA_TEAM_CREDENTIALS"] = previous


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--run-id", default=uuid.uuid4().hex[:12])
    args = parser.parse_args()
    require(bool(re.fullmatch(r"[A-Za-z0-9_-]{8,64}", args.run_id)), "invalid_run_id")
    import_user_environment((*GITHUB_VARIABLES, "GITHUB_BRANCH", "SMARTSHEET_DOCID", "ARENA_V04_SMARTSHEET_DOCID"))
    if not args.execute:
        print(json.dumps({"mode": "dry_run", "writes": False, "report": configuration_report(),
            "execute_requires": "dedicated GitHub App repository and isolated v0.4 sandbox",
            "would_test": "two teams, two versions, idempotency, isolation, expiry, registry recovery"},
            ensure_ascii=False, indent=2))
        return 0
    logging.getLogger("mcp").setLevel(logging.CRITICAL)
    data_dir = Path(__file__).resolve().parents[1] / ".arena" / "v04-acceptance" / args.run_id
    try:
        report = asyncio.run(execute(args.run_id, data_dir))
    except Exception as exc:
        report = {"mode": "real_acceptance_attempt", "state": "failed", "run_id": args.run_id,
            "error_type": type(exc).__name__,
            "code": failure_code(exc),
            "production_cutover": False}
        print(json.dumps(report, ensure_ascii=False))
        return 1
    (data_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

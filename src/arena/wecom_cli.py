"""官方企微 CLI 子进程适配。调用真实 exe，避免 cmd 对 JSON 进行二次解释。"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from arena.wecom_auth import import_user_environment


class WecomError(RuntimeError):
    def __init__(self, code: Any):
        self.code = code
        super().__init__(f"企业微信接口未成功，错误码：{code}")


class WecomCLI:
    def __init__(self):
        import_user_environment()
        override = os.environ.get("WECOM_CLI_EXECUTABLE")
        command = override or shutil.which("wecom-cli.exe") or shutil.which("wecom-cli")
        if command and Path(command).suffix.lower() in (".cmd", ".ps1"):
            candidate = (
                Path(command).parent
                / "node_modules/@wecom/cli/node_modules/@wecom/cli-win32-x64/bin/wecom-cli.exe"
            )
            command = str(candidate) if candidate.is_file() else None
        if not command:
            raise WecomError("cli_executable_missing")
        self.command = command

    def call(self, *command: str, payload: dict | None = None, dry_run: bool = False) -> dict:
        args = [self.command, *command]
        if payload is not None:
            args += ["--json", json.dumps(payload, ensure_ascii=False)]
        if dry_run:
            args.append("--dry-run")
        result = subprocess.run(
            args, capture_output=True, timeout=45, text=True, encoding="utf-8", errors="replace"
        )
        try:
            value = json.loads(result.stdout)
        except ValueError:
            raise WecomError("invalid_json_response") from None
        if not isinstance(value, dict):
            raise WecomError("invalid_response_shape")
        if "error" in value:
            raise WecomError(value["error"].get("code", "unknown_error"))
        if value.get("errcode", 0) != 0 or result.returncode:
            raise WecomError(value.get("errcode", "cli_failed"))
        return value


def user_setting(name: str) -> str:
    import_user_environment((name,))
    return os.environ.get(name, "")


def save_setting(name: str, value: str) -> None:
    allowed = {
        "SMARTSHEET_DOCID",
        "SMARTSHEET_URL",
        "SHEET_WORKS",
        "SHEET_VERSIONS",
        "SHEET_DUTY",
        "SHEET_FEEDBACK",
        "ADMIN_USERIDS",
        "STAFF_USERIDS",
    }
    if name not in allowed or not value:
        raise ValueError("配置项不允许或为空")
    if os.name == "nt":
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
    os.environ[name] = value


def fields(spec: list[tuple[str, str]]) -> list[dict]:
    return [{"field_title": title, "field_type": kind} for title, kind in spec]


SHEETS = {
    "作品": fields(
        [
            ("作品ID", "text"),
            ("作品名", "text"),
            ("队名", "text"),
            ("成员", "text"),
            ("别名", "text"),
            ("简介", "text"),
            ("最新版本", "number"),
            ("仓库链接", "url"),
            ("密钥哈希", "text"),
            ("状态", "text"),
        ]
    ),
    "版本": fields(
        [
            ("作品ID", "text"),
            ("版本号", "number"),
            ("commit SHA", "text"),
            ("tag", "text"),
            ("提交时间", "date_time"),
            ("来源", "text"),
            ("内容哈希", "text"),
            ("检查结果", "text"),
            ("说明", "text"),
        ]
    ),
    "值班": fields(
        [
            ("开始时间", "date_time"),
            ("结束时间", "date_time"),
            ("事项类别", "text"),
            ("负责人姓名", "text"),
            ("负责人 userid", "text"),
        ]
    ),
    "反馈": fields(
        [
            ("时间", "date_time"),
            ("提问人 userid", "text"),
            ("角色", "text"),
            ("问题", "text"),
            ("机器人回答", "text"),
            ("使用的工具", "text"),
            ("是否转人工", "checkbox"),
            ("转给谁", "text"),
            ("评价", "text"),
            ("处理结果", "text"),
            ("feedback_id", "text"),
        ]
    ),
}
ENV_SHEETS = {"作品": "SHEET_WORKS", "版本": "SHEET_VERSIONS", "值班": "SHEET_DUTY", "反馈": "SHEET_FEEDBACK"}


def provision() -> dict:
    cli = WecomCLI()
    identity = cli.call("identity", "whoami")
    human = identity.get("extra_identity_context", "").split("授权真人用户身份：")[-1]
    match = re.search(r"ID：?\s*(\S+)|ID:\s*(\S+)", human)
    if match and not user_setting("ADMIN_USERIDS"):
        operator_id = match.group(1) or match.group(2)
        save_setting("ADMIN_USERIDS", operator_id)
        save_setting("STAFF_USERIDS", operator_id)
    docid = user_setting("SMARTSHEET_DOCID")
    if not docid:
        created = cli.call(
            "smartsheet",
            "create",
            payload={
                "name": "ABF · Arena 比赛运行层 Demo",
                "sheet_title": "作品",
                "fields": SHEETS["作品"],
            },
        )
        if not created.get("docid"):
            raise WecomError("create_missing_docid")
        docid = created["docid"]
        save_setting("SMARTSHEET_DOCID", docid)
        if created.get("url"):
            save_setting("SMARTSHEET_URL", created["url"])
    snapshot = cli.call("smartsheet", "sheets", "list", payload={"docid": docid})
    existing = {sheet["title"]: sheet for sheet in snapshot.get("sheets", [])}
    for title, definition in SHEETS.items():
        if title not in existing:
            cli.call(
                "smartsheet",
                "sheets",
                "add",
                payload={"docid": docid, "sheet_title": title, "type": "add", "fields": definition},
            )
    snapshot = cli.call("smartsheet", "sheets", "list", payload={"docid": docid})
    existing = {sheet["title"]: sheet for sheet in snapshot.get("sheets", [])}
    summary = []
    for title, definition in SHEETS.items():
        if title not in existing:
            raise WecomError("sheet_missing_after_create")
        save_setting(ENV_SHEETS[title], existing[title]["sheet_id"])
        actual = cli.call(
            "smartsheet", "fields", "list", payload={"docid": docid, "sheet_title": title, "limit": 100}
        )
        actual_fields = actual.get("fields", [])
        names = {field["field_title"] for field in actual_fields}
        if not {field["field_title"] for field in definition}.issubset(names):
            raise WecomError("field_readback_mismatch")
        views = cli.call(
            "smartsheet", "views", "list", payload={"docid": docid, "sheet_title": title, "limit": 100}
        ).get("views", [])
        if views:
            widths = [
                {
                    "field_title": field["field_title"],
                    "width": 400
                    if field["field_title"] in ("问题", "机器人回答", "说明", "简介")
                    else (120 if field["field_type"] in ("number", "checkbox") else 160),
                }
                for field in definition
            ]
            cli.call(
                "smartsheet",
                "views",
                "update",
                payload={
                    "docid": docid,
                    "sheet_title": title,
                    "type": "update",
                    "views": [{"view_id": views[0]["view_id"], "col_infos": widths}],
                },
            )
        summary.append({"name": title, "fields_verified": len(definition)})
    return {
        "name": "ABF · Arena 比赛运行层 Demo",
        "url": user_setting("SMARTSHEET_URL"),
        "sheets": summary,
        "state": "structure_created_and_read_back",
    }

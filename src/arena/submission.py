import asyncio
import base64
import binascii
import hashlib
import json
import os
import re
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import PurePosixPath

from pydantic import BaseModel, Field, field_validator

from arena.config import Settings
from arena.operations import OperationJournal
from arena.ports.registry import Registry
from arena.ports.writer import ArtifactWriter
from arena.store import now_iso


class InputFile(BaseModel):
    path: str
    content: str
    encoding: str = "utf-8"


class Submission(BaseModel):
    description: str = Field(min_length=10, max_length=2000)
    title: str | None = Field(default=None, max_length=200)
    files: list[InputFile] = Field(min_length=1, max_length=1000)
    submission_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{8,100}$")

    @field_validator("description", "title", "submission_id")
    @classmethod
    def reject_credentials(cls, value: str | None) -> str | None:
        if value is not None and contains_credential(value.encode()):
            raise ValueError("提交元数据疑似包含凭据，请移除后重试")
        return value


def contains_credential(data: bytes) -> bool:
    if re.search(rb"(?:hk_[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9_-]{20,}|-----BEGIN .*PRIVATE KEY-----)", data):
        return True
    # Protect configured credentials even when a provider uses an unfamiliar prefix.
    for name, value in os.environ.items():
        if len(value) >= 12 and re.search(r"(?:SECRET|TOKEN|PRIVATE_KEY|API_KEY|TEAM_KEY)$", name):
            if value.encode() in data:
                return True
    return False


def collect_files(items: list[InputFile], limit: int) -> tuple[dict[str, bytes], list[str], str]:
    files: dict[str, bytes] = {}
    portable_names: set[str] = set()
    warnings = []
    total = 0
    for item in items:
        name = item.path
        path = PurePosixPath(name)
        parts = name.split("/")
        if (
            not name
            or len(name) > 240
            or path.is_absolute()
            or "\\" in name
            or any(part in ("", ".", "..") or part.endswith((" ", ".")) for part in parts)
            or any(ord(c) < 32 for c in name)
            or any(c in name for c in ':*?"<>|')
            or any(part.lower() == ".git" for part in parts)
            or any(re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?", part) for part in parts)
        ):
            raise ValueError("文件路径不合法")
        if name.casefold() == "submission.json":
            raise ValueError("SUBMISSION.json 是系统保留文件")
        if name.casefold() in portable_names:
            raise ValueError("文件路径重复（含大小写冲突）")
        portable_names.add(name.casefold())
        if item.encoding == "utf-8":
            data = item.content.encode("utf-8")
        elif item.encoding == "base64":
            try:
                data = base64.b64decode(item.content, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise ValueError("base64 内容不合法") from exc
        else:
            raise ValueError("encoding 必须为 utf-8 或 base64")
        total += len(data)
        if len(data) >= 50 * 1024 * 1024 or total > limit:
            raise ValueError("作品大小超过限制")
        # demo 采用更严格规则：疑似凭据拒收，避免将真实密钥写入作品 Git。
        if path.name.startswith(".env") or contains_credential(data):
            raise ValueError("文件疑似包含凭据，请移除后重试")
        files[name] = data
    if "README.md" not in files:
        raise ValueError("根目录必须包含 README.md")
    try:
        readme = files["README.md"].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("README.md 必须是 UTF-8 文本") from exc
    if len(readme) < 200:
        warnings.append("README 少于 200 字，请补充运行说明")
    for name in files:
        if any(
            parent.as_posix().casefold() in portable_names
            for parent in PurePosixPath(name).parents
            if str(parent) != "."
        ):
            raise ValueError("文件路径与目录冲突")
    digest = hashlib.sha256()
    for name in sorted(files):
        encoded = name.encode()
        digest.update(len(encoded).to_bytes(4, "big") + encoded)
        digest.update(len(files[name]).to_bytes(8, "big") + files[name])
    return files, warnings, digest.hexdigest()


class SubmissionService:
    def __init__(self, settings: Settings, store: Registry, writer: ArtifactWriter):
        self.settings, self.store, self.writer = settings, store, writer
        self.lock = asyncio.Lock()
        self.attempts: dict[str, deque[float]] = defaultdict(deque)
        self.journal = OperationJournal(settings.data_dir / "operations.sqlite3")

    @staticmethod
    def result(item: dict) -> dict:
        return {k: item[k] for k in ("work_id", "version", "tag", "commit_sha", "repo_link", "checks", "submission_id")}

    async def reconcile(self) -> dict:
        """Replay registry writes from immutable Git evidence, never rewrite Git."""
        recovered, pending = [], []
        async with self.lock, self.operation_lock():
            for operation in self.journal.pending():
                item = operation["payload"]
                try:
                    evidence = await self.writer.recover(item["work_id"], item["version"])
                    if evidence is None:
                        pending.append(operation["submission_id"])
                        continue
                    self.validate_evidence(item, evidence)
                    item.update({k: evidence[k] for k in ("tag", "commit_sha", "repo_link")})
                    self.register(item)
                    recovered.append(operation["submission_id"])
                except Exception:
                    pending.append(operation["submission_id"])
        return {"reconciled": recovered, "pending": pending}

    @asynccontextmanager
    async def operation_lock(self):
        with self.journal.exclusive():
            yield

    @staticmethod
    def validate_evidence(item: dict, evidence: dict):
        meta = evidence.get("metadata", {})
        if any(meta.get(k) != item.get(k) for k in ("submission_id", "work_id", "version", "content_hash", "fingerprint")):
            raise RuntimeError("Git tag 与操作日志冲突，需人工复核")

    def register(self, item: dict):
        history = self.store.versions(item["work_id"])
        old = next((v for v in history if v["version"] == item["version"]), None)
        if old and any(old[k] != item[k] for k in ("tag", "commit_sha", "content_hash")):
            raise RuntimeError("登记版本冲突，需人工复核")
        # Cloud Registry also repairs a version-created / pointer-update-failed split.
        if (not old or self.store.require(item["work_id"])["latest"] < item["version"]
                or old.get("registration_status", "registered") != "registered"):
            self.store.record_submission(item["work_id"], item.get("title"), item)
        self.journal.save(item["submission_id"], item["work_id"], item["fingerprint"], "registered", item)

    async def submit(self, work_id: str, request: Submission, key: str | None = None) -> dict:
        files, warnings, digest = collect_files(request.files, self.settings.max_inline_bytes)
        submission_id = request.submission_id or uuid.uuid4().hex
        fingerprint = hashlib.sha256(json.dumps(
            [digest, request.title, request.description], ensure_ascii=False
        ).encode()).hexdigest()
        async with self.lock, self.operation_lock():
            work = self.store.get(work_id)
            if not work or work["status"] == "已禁用":
                raise ValueError("队伍已禁用或不存在")
            if key is not None and (self.store.authenticate(key) or {}).get("id") != work_id:
                raise ValueError("队伍密钥已失效")
            operation = self.journal.get(submission_id)
            if operation:
                if operation["work_id"] != work_id or operation["fingerprint"] != fingerprint:
                    raise ValueError("submission_id 已被不同请求使用")
                item = operation["payload"]
                if operation["state"] == "registered":
                    return self.result(item)
                evidence = await self.writer.recover(work_id, item["version"])
                if evidence:
                    self.validate_evidence(item, evidence)
                    item.update({k: evidence[k] for k in ("tag", "commit_sha", "repo_link")})
                    self.register(item)
                    return self.result(item)
            elif self.journal.pending(work_id):
                raise RuntimeError("该队有待恢复提交，请先对账或使用原 submission_id 重试")
            if datetime.now(timezone.utc) > self.settings.submission_deadline:
                raise ValueError("已过截止时间")
            # 每队每分钟 5 次；内部 demo/并发测试可直接绕过限流以验证串行机制。
            if key is not None:
                attempts = self.attempts[work_id]
                current = time.monotonic()
                while attempts and current - attempts[0] >= 60:
                    attempts.popleft()
                if len(attempts) >= 5:
                    raise ValueError("提交过于频繁，请一分钟后重试")
                attempts.append(current)
            history = self.store.versions(work_id)
            if history and history[-1]["content_hash"] == digest:
                raise ValueError("作品内容没有变化")
            version = operation["payload"]["version"] if operation else work["latest"] + 1
            item = operation["payload"] if operation else {
                "work_id": work_id,
                "version": version,
                "submitted_at": now_iso(),
                "description": request.description,
                "content_hash": digest,
                "checks": ["阻断项通过", *warnings],
                "source": "files",
                "submission_id": submission_id,
                "fingerprint": fingerprint,
                "title": request.title,
                "policy_version": self.settings.policy_release,
            }
            self.journal.save(submission_id, work_id, fingerprint, "planned", item)
            try:
                written = await self.writer.write(work_id, version, files, item)
            except Exception:
                raise RuntimeError(f"作品写入未确认；请保持原内容并使用 submission_id={submission_id} 重试或对账") from None
            item.update(written)
            self.journal.save(submission_id, work_id, fingerprint, "written", item)
            try:
                self.register(item)
            except Exception:
                # The durable journal already holds credential-free recovery metadata.
                raise RuntimeError(f"Git 已保存，登记失败；请执行 arena reconcile 或使用 submission_id={submission_id} 重试") from None
            return self.result(item)

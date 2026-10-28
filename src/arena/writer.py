import asyncio
import json
import re
import shutil
from pathlib import Path


class LocalGitWriter:
    """实际 Git commit/tag 的本地替身，不向 GitHub 推送。"""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    async def git(self, *args: str) -> str:
        process = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            str(self.root),
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await process.communicate()
        if process.returncode:
            # Git stderr 不包含认证信息，因为这里仅对专用本地仓库执行白名单命令。
            raise RuntimeError(f"local git failed: {err.decode(errors='replace')[:300]}")
        return out.decode().strip()

    async def start(self) -> None:
        if not (self.root / ".git").exists():
            await self.git("init", "--initial-branch=main")
            await self.git(
                "-c",
                "user.name=Arena Demo",
                "-c",
                "user.email=arena@localhost",
                "commit",
                "--allow-empty",
                "-m",
                "arena init",
            )

    async def write(self, work_id: str, version: int, files: dict[str, bytes], metadata: dict) -> dict:
        if not re.fullmatch(r"H-[0-9]{3,}", work_id) or version < 1:
            raise ValueError("invalid work/version")
        await self.start()
        tag = f"{work_id}/v{version}"
        # 停机后未登记的提交不可静默覆盖：保留现场，交由管理员核对。
        tags = (await self.git("tag", "--list", tag)).splitlines()
        if tag in tags:
            raise RuntimeError("该版本 tag 已存在，请核对登记表与 Git，避免覆盖未登记的提交")
        target = self.root / "works" / work_id
        if target.exists():
            # target 由服务生成的作品编号组成，并且必须处于专用作品仓库内。
            if target.resolve().parent != (self.root / "works").resolve():
                raise RuntimeError("invalid managed work directory")
            shutil.rmtree(target)
        target.mkdir(parents=True)
        for name, data in files.items():
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (target / "SUBMISSION.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        await self.git("add", "--force", "--all", "--", f"works/{work_id}")
        await self.git(
            "-c",
            "user.name=Arena Demo",
            "-c",
            "user.email=arena@localhost",
            "commit",
            "-m",
            f"{work_id} v{version}",
        )
        sha = await self.git("rev-parse", "HEAD")
        await self.git("tag", tag, sha)
        return {"tag": tag, "commit_sha": sha, "repo_link": str(target)}

    async def recover(self, work_id: str, version: int) -> dict | None:
        if not re.fullmatch(r"H-[0-9]{3,}", work_id) or version < 1:
            raise ValueError("invalid work/version")
        await self.start()
        tag = f"{work_id}/v{version}"
        if tag not in (await self.git("tag", "--list", tag)).splitlines():
            return None
        sha = await self.git("rev-parse", tag)
        meta = json.loads(await self.git("show", f"{tag}:works/{work_id}/SUBMISSION.json"))
        return {"tag": tag, "commit_sha": sha, "repo_link": str(self.root / "works" / work_id), "metadata": meta}

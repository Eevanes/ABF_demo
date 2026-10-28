"""GitHub App artifact writer. Immutable tags and compare-and-swap branch updates."""

import base64
import json
import os
import re
import time
from urllib.parse import quote

import httpx
import jwt


class GitHubWriteError(RuntimeError):
    pass


class GitHubAppWriter:
    def __init__(self, repo: str, app_id: str, installation_id: str, private_key: str,
                 branch: str = "main", client: httpx.AsyncClient | None = None):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            raise ValueError("GITHUB_REPO must be owner/repo")
        if not app_id or not installation_id or not private_key:
            raise ValueError("GitHub App 环境配置不完整")
        self.repo, self.app_id, self.installation_id = repo, app_id, installation_id
        self.private_key, self.branch, self.client = private_key, branch, client
        self.token = ""
        self.token_until = 0.0

    @classmethod
    def from_environment(cls):
        return cls(os.environ.get("GITHUB_REPO", ""), os.environ.get("GITHUB_APP_ID", ""),
                   os.environ.get("GITHUB_INSTALLATION_ID", ""), os.environ.get("GITHUB_APP_PRIVATE_KEY", ""),
                   branch=os.environ.get("GITHUB_BRANCH", "main"))

    async def start(self) -> None:
        # No network or token acquisition until the first explicit operation.
        return None

    async def request(self, method: str, path: str, data: dict | None = None,
                      missing: bool = False, app_token: str | None = None) -> dict | None:
        if app_token is None:
            if time.time() >= self.token_until:
                now = int(time.time())
                signed = jwt.encode({"iat": now - 60, "exp": now + 540, "iss": self.app_id},
                                    self.private_key, algorithm="RS256")
                issued = await self.request("POST", f"/app/installations/{quote(self.installation_id, safe='')}/access_tokens",
                                            {"repositories": [self.repo.split('/')[1]], "permissions": {"contents": "write"}},
                                            app_token=signed)
                if not issued or not issued.get("token"):
                    raise GitHubWriteError("github_installation_token_missing")
                self.token = issued["token"]
                self.token_until = time.time() + 3000
            app_token = self.token
        headers = {"Authorization": "Bearer " + app_token, "Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28"}
        try:
            if self.client:
                response = await self.client.request(method, "https://api.github.com" + path, json=data, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                    response = await client.request(method, "https://api.github.com" + path, json=data, headers=headers)
        except httpx.HTTPError:
            raise GitHubWriteError("github_transport_error") from None
        if missing and response.status_code == 404:
            return None
        if response.status_code >= 400:
            # Never surface response bodies or request objects containing credentials.
            raise GitHubWriteError(f"github_http_{response.status_code}")
        return response.json()

    @property
    def prefix(self) -> str:
        return f"/repos/{self.repo}"

    @staticmethod
    def validate(work_id: str, version: int):
        if not re.fullmatch(r"H-[0-9]{3,}", work_id) or version < 1:
            raise ValueError("invalid work/version")

    async def ref(self, ref: str) -> dict | None:
        return await self.request("GET", self.prefix + "/git/ref/" + quote(ref, safe="/"), missing=True)

    async def metadata(self, work_id: str, sha: str) -> dict | None:
        value = await self.request("GET", self.prefix + f"/contents/works/{work_id}/SUBMISSION.json?ref={quote(sha, safe='')}", missing=True)
        if not value:
            return None
        try:
            return json.loads(base64.b64decode(value["content"]))
        except (ValueError, KeyError):
            raise GitHubWriteError("github_invalid_metadata") from None

    def evidence(self, work_id: str, version: int, sha: str, metadata: dict) -> dict:
        tag = f"{work_id}/v{version}"
        return {"tag": tag, "commit_sha": sha,
                "repo_link": f"https://github.com/{self.repo}/tree/{quote(tag, safe='')}/works/{work_id}",
                "metadata": metadata}

    async def tag(self, tag: str, sha: str):
        try:
            await self.request("POST", self.prefix + "/git/refs", {"ref": "refs/tags/" + tag, "sha": sha})
        except GitHubWriteError:
            existing = await self.ref("tags/" + tag)
            if not existing or existing["object"]["sha"] != sha:
                raise GitHubWriteError("github_tag_conflict") from None

    async def recover(self, work_id: str, version: int) -> dict | None:
        self.validate(work_id, version)
        existing = await self.ref(f"tags/{work_id}/v{version}")
        if existing:
            sha = existing["object"]["sha"]
            meta = await self.metadata(work_id, sha)
            if not meta:
                raise GitHubWriteError("github_tag_metadata_missing")
            return self.evidence(work_id, version, sha, meta)
        # Recover the crash window after branch update but before tag creation.
        head = await self.ref("heads/" + self.branch)
        if not head:
            raise GitHubWriteError("github_initialized_branch_required")
        sha = head["object"]["sha"]
        meta = await self.metadata(work_id, sha)
        if meta and meta.get("work_id") == work_id and meta.get("version") == version:
            await self.tag(f"{work_id}/v{version}", sha)
            return self.evidence(work_id, version, sha, meta)
        return None

    async def write(self, work_id: str, version: int, files: dict[str, bytes], metadata: dict) -> dict:
        self.validate(work_id, version)
        old = await self.recover(work_id, version)
        if old:
            if old["metadata"].get("submission_id") != metadata.get("submission_id") or old["metadata"].get("fingerprint") != metadata.get("fingerprint"):
                raise GitHubWriteError("github_tag_conflict")
            return {k: old[k] for k in ("tag", "commit_sha", "repo_link")}
        entries = []
        for name, content in sorted(files.items()):
            blob = await self.request("POST", self.prefix + "/git/blobs",
                                      {"content": base64.b64encode(content).decode(), "encoding": "base64"})
            entries.append({"path": name, "mode": "100644", "type": "blob", "sha": blob["sha"]})  # type: ignore[index]
        meta_blob = await self.request("POST", self.prefix + "/git/blobs", {
            "content": json.dumps(metadata, ensure_ascii=False), "encoding": "utf-8"})
        entries.append({"path": "SUBMISSION.json", "mode": "100644", "type": "blob", "sha": meta_blob["sha"]})  # type: ignore[index]
        subtree = await self.request("POST", self.prefix + "/git/trees", {"tree": entries})
        for attempt in range(3):
            head = await self.ref("heads/" + self.branch)
            if not head:
                raise GitHubWriteError("github_initialized_branch_required")
            parent = head["object"]["sha"]
            commit = await self.request("GET", self.prefix + "/git/commits/" + parent)
            tree = await self.request("POST", self.prefix + "/git/trees", {
                "base_tree": commit["tree"]["sha"],  # type: ignore[index]
                "tree": [{"path": f"works/{work_id}", "mode": "040000", "type": "tree", "sha": subtree["sha"]}],  # type: ignore[index]
            })
            created = await self.request("POST", self.prefix + "/git/commits", {
                "message": f"{work_id} v{version}", "tree": tree["sha"], "parents": [parent]})  # type: ignore[index]
            sha = created["sha"]  # type: ignore[index]
            try:
                await self.request("PATCH", self.prefix + "/git/refs/heads/" + quote(self.branch, safe="/"), {"sha": sha, "force": False})
            except GitHubWriteError as exc:
                if str(exc) in ("github_http_409", "github_http_422") and attempt < 2:
                    continue
                raise
            await self.tag(f"{work_id}/v{version}", sha)
            return {k: v for k, v in self.evidence(work_id, version, sha, metadata).items() if k != "metadata"}
        raise GitHubWriteError("github_branch_conflict")

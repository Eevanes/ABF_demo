import base64
import json
import time

import httpx
import pytest

from arena.adapters.github_app_writer import GitHubAppWriter, GitHubWriteError


class GitHubFixture:
    def __init__(self, conflict=False, crash_tag=False):
        self.head = "initial"
        self.tags = {}
        self.meta = None
        self.commits = 0
        self.conflict = conflict
        self.crash_tag = crash_tag
        self.trees = []
        self.blobs = []

    def call(self, request):
        path = request.url.path.split("/repos/test/artifacts")[-1]
        data = json.loads(request.content) if request.content else {}
        if path == "/git/ref/heads/main":
            return httpx.Response(200, json={"object": {"sha": self.head}})
        if path.startswith("/git/ref/tags/"):
            tag = path.split("/tags/")[-1]
            return httpx.Response(200, json={"object": {"sha": self.tags[tag]}}) if tag in self.tags else httpx.Response(404)
        if path.startswith("/contents/"):
            return httpx.Response(200, json={"content": base64.b64encode(json.dumps(self.meta).encode()).decode()}) if self.meta else httpx.Response(404)
        if path == "/git/blobs":
            self.blobs.append(data)
            if data["encoding"] == "utf-8":
                self.pending_meta = json.loads(data["content"])
            return httpx.Response(201, json={"sha": f"blob{len(self.blobs)}"})
        if path == "/git/trees":
            self.trees.append(data)
            return httpx.Response(201, json={"sha": f"tree{len(self.trees)}"})
        if path.startswith("/git/commits/"):
            return httpx.Response(200, json={"tree": {"sha": "root-" + self.head}})
        if path == "/git/commits":
            self.commits += 1
            return httpx.Response(201, json={"sha": f"commit{self.commits}"})
        if path == "/git/refs/heads/main":
            assert data["force"] is False
            if self.conflict:
                self.conflict = False
                self.head = "other-team-commit"
                return httpx.Response(422, json={"message": "not fast-forward"})
            self.head, self.meta = data["sha"], self.pending_meta
            return httpx.Response(200, json={"object": {"sha": self.head}})
        if path == "/git/refs":
            if self.crash_tag:
                self.crash_tag = False
                raise httpx.ConnectError("simulated interruption")
            self.tags[data["ref"].replace("refs/tags/", "")] = data["sha"]
            return httpx.Response(201, json={"object": {"sha": data["sha"]}})
        raise AssertionError((request.method, path))


def metadata():
    return {"work_id": "H-001", "version": 1, "submission_id": "request0001", "fingerprint": "hash", "content_hash": "content"}


async def test_branch_conflict_rebases_without_changing_other_work():
    remote = GitHubFixture(conflict=True)
    async with httpx.AsyncClient(transport=httpx.MockTransport(remote.call)) as client:
        writer = GitHubAppWriter("test/artifacts", "app", "installation", "unused", client=client)
        writer.token, writer.token_until = "test-only", time.time() + 1000
        result = await writer.write("H-001", 1, {"README.md": b"test", "src/main.py": b"pass"}, metadata())
        assert result["commit_sha"] == "commit2"
        assert remote.tags == {"H-001/v1": "commit2"}
        assert remote.trees[-1]["base_tree"] == "root-other-team-commit"
        assert [item["path"] for item in remote.trees[-1]["tree"]] == ["works/H-001"]
        assert await writer.write("H-001", 1, {"README.md": b"test"}, metadata()) == result
        assert remote.commits == 2
        with pytest.raises(GitHubWriteError, match="conflict"):
            await writer.write("H-001", 1, {}, metadata() | {"fingerprint": "changed"})


async def test_branch_success_tag_failure_recovers_without_new_commit():
    remote = GitHubFixture(crash_tag=True)
    async with httpx.AsyncClient(transport=httpx.MockTransport(remote.call)) as client:
        writer = GitHubAppWriter("test/artifacts", "app", "installation", "unused", client=client)
        writer.token, writer.token_until = "test-only", time.time() + 1000
        with pytest.raises(GitHubWriteError):
            await writer.write("H-001", 1, {"README.md": b"test"}, metadata())
        evidence = await writer.recover("H-001", 1)
        assert evidence["metadata"] == metadata()
        assert remote.tags == {"H-001/v1": "commit1"}
        assert remote.commits == 1


async def test_app_token_scoped_and_errors_do_not_echo_secrets(monkeypatch):
    calls = []
    monkeypatch.setattr("arena.adapters.github_app_writer.jwt.encode", lambda *a, **k: "test-jwt")
    def transport(request):
        calls.append(request)
        if "/access_tokens" in request.url.path:
            assert json.loads(request.content) == {"repositories": ["artifacts"], "permissions": {"contents": "write"}}
            return httpx.Response(201, json={"token": "secret-test-only"})
        return httpx.Response(403, json={"message": "secret-test-only"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        writer = GitHubAppWriter("test/artifacts", "app", "installation", "unused", client=client)
        with pytest.raises(GitHubWriteError) as error:
            await writer.recover("H-001", 1)
        assert str(error.value) == "github_http_403"
        assert len(calls) == 2

"""Exercise the acceptance driver offline, without claiming cloud acceptance."""

import base64
import importlib.util
from pathlib import Path

import pytest


def load_driver():
    spec = importlib.util.spec_from_file_location("v04_rehearsal",
        Path(__file__).resolve().parents[1] / "scripts" / "v04_submission_acceptance.py")
    assert spec is not None and spec.loader is not None
    driver = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(driver)
    return driver


def test_mcp_task_group_keeps_safe_diagnostic_without_remote_messages():
    driver = load_driver()
    private_error = RuntimeError("synthetic-private-response-do-not-print")
    wrapped = ExceptionGroup("mcp", [private_error, ExceptionGroup("client", [
        driver.AcceptanceError("ledger_mismatch")])])
    assert driver.failure_code(wrapped) == "ledger_mismatch"
    assert driver.failure_code(private_error) == "external_check_failed"


async def test_two_teams_two_versions_and_reconcile_driver(bundle):
    driver = load_driver()
    settings, registry, writer, _ = bundle
    teams = {}
    for index in (1, 2):
        work, key = registry.register(f"虚构验收队{index}", "协议验证")
        teams[work["id"]] = key

    class CloudContractStore:
        # The legacy offline Store predates submission_id in version rows.
        # Add that cloud-contract field only in this explicit offline test double.
        def __init__(self):
            self.ids = {}

        def __getattr__(self, name):
            return getattr(registry, name)

        def record_submission(self, work_id, title, item):
            registry.record_submission(work_id, title, item)
            self.ids[(work_id, item["version"])] = item["submission_id"]

        def versions(self, work_id):
            return [row | {"submission_id": self.ids[(work_id, row["version"])]}
                for row in registry.versions(work_id)]

    async def verify_local_artifact(writer, item, payload):
        sha = await writer.git("rev-parse", item["tag"])
        assert sha == item["commit_sha"]
        for file in payload["files"]:
            assert await writer.git("show", f"{sha}:works/{item['work_id']}/{file['path']}") == file["content"].strip()
        if item["version"] == 2:
            assert "src/old.py" not in await writer.git("ls-tree", "-r", "--name-only", sha,
                f"works/{item['work_id']}")

    report = await driver.exercise(settings, CloudContractStore(), writer, teams, "offline-test", verify_local_artifact)
    assert all(report["checks"].values())
    assert len(report["submissions"]) == 4
    assert len((await writer.git("tag", "--list")).splitlines()) == 4
    # This report is test-local and is never written as external acceptance evidence.
    assert report["remote_https"] == "not_verified"


@pytest.mark.parametrize("change", ["removed", "renamed", "missing"])
async def test_github_diff_readback_handles_rename_detection(change):
    driver = load_driver()
    payload = driver.request_payload("offline-test", "H-001", 2)
    item = {"work_id": "H-001", "version": 2, "tag": "H-001/v2", "commit_sha": "test-sha",
        "submission_id": payload["submission_id"]}

    class ReadbackFixture:
        prefix = "/repos/test/artifacts"

        async def ref(self, ref):
            return {"object": {"sha": "test-sha"}}

        async def metadata(self, work_id, sha):
            return item

        async def request(self, method, path, missing=False):
            assert method == "GET"
            if "/compare/" in path:
                if change == "removed":
                    return {"files": [{"filename": "works/H-001/src/old.py", "status": "removed"}]}
                if change == "renamed":
                    return {"files": [{"filename": "works/H-001/src/main.py",
                        "previous_filename": "works/H-001/src/old.py", "status": "renamed"}]}
                return {"files": []}
            if "/src/old.py?" in path:
                assert missing
                return None
            file = next(file for file in payload["files"] if "/" + file["path"] + "?" in path)
            return {"content": base64.b64encode(file["content"].encode()).decode()}

    if change == "missing":
        with pytest.raises(driver.AcceptanceError, match="version_diff_missing"):
            await driver.verify_artifact(ReadbackFixture(), item, payload)
    else:
        await driver.verify_artifact(ReadbackFixture(), item, payload)

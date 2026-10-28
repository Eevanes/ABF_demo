import pytest

from arena.operations import OperationJournal
from arena.submission import InputFile, Submission, SubmissionService


def submission(identifier="request_0001", content="one"):
    return Submission(description="提交恢复机制的有效版本说明", title="恢复后的新标题", submission_id=identifier,
                      files=[InputFile(path="README.md", content=content)])


async def test_same_id_replay_and_changed_request_rejected(bundle):
    _, store, writer, service = bundle
    work, key = store.register("恢复队", "原标题")
    first = await service.submit(work["id"], submission(), key)
    assert await service.submit(work["id"], submission(), key) == first
    assert len(store.versions(work["id"])) == 1
    assert len((await writer.git("tag", "--list")).splitlines()) == 1
    with pytest.raises(ValueError, match="不同请求"):
        await service.submit(work["id"], submission(content="changed"), key)
    store.reset_key(work["id"])
    with pytest.raises(ValueError, match="失效"):
        await service.submit(work["id"], submission(), key)


async def test_git_saved_registry_failed_restart_recovery(bundle, monkeypatch):
    settings, store, writer, service = bundle
    work, key = store.register("恢复队", "原标题")
    original = store.record_submission
    monkeypatch.setattr(store, "record_submission", lambda *a: (_ for _ in ()).throw(RuntimeError("offline")))
    with pytest.raises(RuntimeError, match="登记失败"):
        await service.submit(work["id"], submission(), key)
    assert store.require(work["id"])["latest"] == 0
    assert len(service.journal.pending()) == 1
    monkeypatch.setattr(store, "record_submission", original)
    restarted = SubmissionService(settings, store, writer)
    assert (await restarted.reconcile())["reconciled"] == ["request_0001"]
    assert store.require(work["id"])["title"] == "恢复后的新标题"
    assert store.require(work["id"])["latest"] == 1
    assert not restarted.journal.pending()
    assert (await restarted.reconcile())["reconciled"] == []
    assert len((await writer.git("tag", "--list")).splitlines()) == 1


async def test_crash_after_git_before_journal_update_recovers(bundle, monkeypatch):
    settings, store, writer, service = bundle
    work, key = store.register("中断队", "作品")
    original_save = service.journal.save
    def crash(identifier, work_id, fingerprint, state, payload):
        if state == "written":
            raise RuntimeError("simulated process exit")
        original_save(identifier, work_id, fingerprint, state, payload)
    monkeypatch.setattr(service.journal, "save", crash)
    with pytest.raises(RuntimeError, match="simulated"):
        await service.submit(work["id"], submission(), key)
    restarted = SubmissionService(settings, store, writer)
    result = await restarted.submit(work["id"], submission(), key)
    assert result["version"] == 1
    assert not restarted.journal.pending()


def test_single_writer_lock(tmp_path):
    first = OperationJournal(tmp_path / "operations.sqlite3")
    second = OperationJournal(tmp_path / "operations.sqlite3")
    with first.exclusive():
        with pytest.raises(RuntimeError, match="单实例"):
            with second.exclusive():
                pass
    with second.exclusive():
        pass


def test_metadata_and_files_cannot_publish_configured_credentials(monkeypatch):
    from arena.submission import collect_files

    value = "synthetic-provider-credential-value"
    monkeypatch.setenv("CUSTOM_API_KEY", value)
    with pytest.raises(ValueError, match="凭据"):
        Submission(description="不应上传此值：" + value, files=[InputFile(path="README.md", content="safe")])
    with pytest.raises(ValueError, match="凭据"):
        collect_files([InputFile(path="README.md", content="credential=" + value)], 1000)


async def test_restart_service_automatically_reconciles(bundle, monkeypatch):
    import asyncio

    import httpx

    from arena.mcp_app import create_app
    from arena.walkthrough import running_server

    settings, store, writer, service = bundle
    work, key = store.register("自动恢复队", "作品")
    original = store.record_submission
    monkeypatch.setattr(store, "record_submission", lambda *a: (_ for _ in ()).throw(RuntimeError("offline")))
    with pytest.raises(RuntimeError, match="登记失败"):
        await service.submit(work["id"], submission(), key)
    monkeypatch.setattr(store, "record_submission", original)
    async with running_server(create_app(settings, store, writer=writer)) as url:
        async with httpx.AsyncClient() as client:
            async with asyncio.timeout(5):
                while (await client.get(url + "/healthz")).status_code != 200:
                    await asyncio.sleep(0.02)
    assert store.require(work["id"])["latest"] == 1
    assert len(store.versions(work["id"])) == 1

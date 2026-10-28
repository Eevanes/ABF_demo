import asyncio
from datetime import datetime, timezone

import pytest

from arena.submission import InputFile, Submission, collect_files


def request(n=0, old=False):
    return Submission(
        description="用于验证提交的有效版本说明。",
        files=[
            InputFile(path="README.md", content=f"# 版本 {n}\n" + "运行说明。" * 50),
            InputFile(path="old.py" if old else "new.py", content=str(n)),
        ],
    )


def test_idempotent_registration_and_reset(bundle):
    _, store, _, _ = bundle
    keys = []
    for i in range(3):
        work, key = store.register(f"队伍{i}", "作品")
        assert work["id"] == f"H-{i + 1:03d}"
        keys.append(key)
        assert "key_hash" not in work
    assert store.register("队伍0", "另一个名字")[1] is None
    assert len(store.works()) == 3
    changed = store.reset_key("H-001")
    assert not store.authenticate(keys[0])
    assert store.authenticate(changed)["id"] == "H-001"
    store.set_status("H-001", True)
    assert store.authenticate(changed) is None


@pytest.mark.parametrize(
    "path", ["../x", "/x", "C:/x", "a\\b", ".git/config", "CON", "a/../x", "a./x", "a//x", "SUBMISSION.json"]
)
def test_unsafe_paths(path):
    with pytest.raises(ValueError):
        collect_files([InputFile(path="README.md", content="ok"), InputFile(path=path, content="x")], 1000)


def test_file_checks():
    with pytest.raises(ValueError, match="README"):
        collect_files([InputFile(path="x", content="x")], 1000)
    with pytest.raises(ValueError, match="大小"):
        collect_files([InputFile(path="README.md", content="x" * 100)], 5)
    with pytest.raises(ValueError, match="base64"):
        collect_files([InputFile(path="README.md", content="!", encoding="base64")], 100)
    with pytest.raises(ValueError, match="凭据"):
        collect_files(
            [InputFile(path="README.md", content="x"), InputFile(path=".env", content="SECRET=dummy")], 100
        )
    with pytest.raises(ValueError, match="冲突"):
        collect_files(
            [InputFile(path="README.md", content="x"), InputFile(path="Readme.md", content="x")], 100
        )
    with pytest.raises(ValueError, match="冲突"):
        collect_files(
            [
                InputFile(path="README.md", content="x"),
                InputFile(path="a", content="x"),
                InputFile(path="a/x", content="x"),
            ],
            100,
        )


async def test_three_versions_and_other_work_unchanged(bundle):
    _, store, writer, service = bundle
    work, key = store.register("甲队", "甲作品")
    other, other_key = store.register("乙队", "乙作品")
    untouched = await service.submit(other["id"], request(99), other_key)
    results = [await service.submit(work["id"], request(i, old=(i == 0)), key) for i in range(3)]
    assert not (writer.root / "works" / work["id"] / "old.py").exists()
    for i, item in enumerate(results):
        assert await writer.git("rev-parse", item["tag"]) == item["commit_sha"]
        source = await writer.git("show", f"{item['tag']}:works/{work['id']}/README.md")
        assert f"版本 {i}" in source
    current = await writer.git("show", f"HEAD:works/{other['id']}/README.md")
    previous = await writer.git("show", f"{untouched['tag']}:works/{other['id']}/README.md")
    assert current == previous
    with pytest.raises(ValueError, match="没有变化"):
        await service.submit(work["id"], request(2), key)


async def test_twenty_concurrent_submissions(bundle):
    _, store, writer, service = bundle
    work, _ = store.register("并发队", "并发作品")
    # 内部测试验证串行版本分配；网络入口的每分钟限流单独验证。
    results = await asyncio.gather(*(service.submit(work["id"], request(i)) for i in range(20)))
    assert sorted(item["version"] for item in results) == list(range(1, 21))
    assert len(set(item["commit_sha"] for item in results)) == 20
    assert len((await writer.git("tag", "--list")).splitlines()) == 20


async def test_deadline_key_recheck_and_rate_limit(bundle):
    settings, store, _, service = bundle
    work, key = store.register("限流队", "限流作品")
    for i in range(5):
        await service.submit(work["id"], request(i), key)
    with pytest.raises(ValueError, match="频繁"):
        await service.submit(work["id"], request(6), key)
    store.reset_key(work["id"])
    with pytest.raises(ValueError, match="失效"):
        await service.submit(work["id"], request(6), key)
    settings.submission_deadline = datetime(2000, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="截止"):
        await service.submit(work["id"], request(7))

import json

import pytest

from arena.cloud_bridge import CloudBridge


class FakeCLI:
    def __init__(self, fail=False):
        self.fail = fail
        self.data = {title: [] for title in ("作品", "版本", "值班", "反馈")}
        self.writes = 0

    def call(self, *command, payload):
        title = payload["sheet_title"]
        if command[-1] == "list":
            return {"records": self.data[title]}
        if self.fail:
            raise RuntimeError("simulated cloud unavailable")
        item = payload["records"][0]
        assert "密钥哈希" not in item["values"]
        self.writes += 1
        record = {"record_id": item.get("record_id", f"r{self.writes}"), "values": item["values"]}
        self.data[title] = [r for r in self.data[title] if r["record_id"] != record["record_id"]] + [record]
        return {"records": [record]}


async def test_cloud_sync_is_idempotent_and_aliases_return(bundle):
    _, store, _, _ = bundle
    work, key = store.register("云端队", "示例作品")
    cli = FakeCLI()
    bridge = CloudBridge(store, cli, "demo-doc")
    await bridge.sync_once()
    assert key not in json.dumps(cli.data)
    assert cli.writes == 1
    await bridge.sync_once()
    assert cli.writes == 1
    cli.data["作品"][0]["values"]["别名"] = [{"type": "text", "text": "手工补充别名"}]
    await bridge.sync_once()
    assert store.require(work["id"])["aliases"] == "手工补充别名"


async def test_failed_sync_is_not_marked_as_delivered(bundle):
    _, store, _, _ = bundle
    store.register("故障队", "示例作品")
    cli = FakeCLI(fail=True)
    bridge = CloudBridge(store, cli, "demo-doc")
    with pytest.raises(RuntimeError):
        await bridge.sync_once()
    assert store.db.execute("SELECT count(*) FROM cloud_sync").fetchone()[0] == 0
    cli.fail = False
    await bridge.sync_once()
    assert bridge.status["state"] == "ready"

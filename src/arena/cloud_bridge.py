"""Demo 的企微登记镜像与别名回流；本阶段仍以本地 SQLite/Git 维护提交事务。"""

import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone

from arena.store import Store, now_iso
from arena.wecom_cli import WecomCLI, WecomError, user_setting

CHINA = timezone(timedelta(hours=8))


def plain(value):
    if isinstance(value, list):
        return "".join(str(part.get("text", "")) for part in value if isinstance(part, dict))
    return value


def cloud_time(value: str) -> str:
    return datetime.fromisoformat(value).astimezone(CHINA).strftime("%Y-%m-%d %H:%M:%S")


class CloudBridge:
    def __init__(self, store: Store, cli=None, docid: str | None = None):
        self.store = store
        self.cli = cli or WecomCLI()
        self.docid = docid or user_setting("SMARTSHEET_DOCID")
        if not self.docid:
            raise ValueError("尚未配置比赛专用智能表格")
        self.status: dict = {"state": "starting", "last_sync": None, "error": None, "writes": 0}
        self.store.db.execute("CREATE TABLE IF NOT EXISTS cloud_sync (entity TEXT PRIMARY KEY, digest TEXT)")
        self.store.db.commit()

    async def call(self, *command, payload):
        return await asyncio.to_thread(self.cli.call, *command, payload=payload)

    async def records(self, title: str) -> list[dict]:
        rows: list[dict] = []
        start = 0
        for _ in range(100):
            response = await self.call(
                "smartsheet",
                "records",
                "list",
                payload={"docid": self.docid, "sheet_title": title, "limit": 1000, "start": start},
            )
            current = response.get("records", [])
            rows.extend(current)
            if not response.get("has_more") and len(current) < 1000:
                return rows
            next_start = response.get("next", start + len(current))
            if not current or not isinstance(next_start, int) or next_start <= start:
                raise ValueError("表格分页未前进")
            start = next_start
        raise ValueError("demo 表格超过分页上限")

    async def upsert(self, title: str, key_field: str, key: str, values: dict, remote: list[dict]):
        entity = f"{title}/{key}"
        digest = hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        known = self.store.db.execute("SELECT digest FROM cloud_sync WHERE entity=?", (entity,)).fetchone()
        found = next((r for r in remote if str(plain(r.get("values", {}).get(key_field, ""))) == key), None)
        if found and known and known[0] == digest:
            return
        item = {"values": values}
        action = "update" if found else "add"
        if found:
            item["record_id"] = found["record_id"]
        result = await self.call(
            "smartsheet",
            "records",
            action,
            payload={"docid": self.docid, "sheet_title": title, "key_type": "field_title", "records": [item]},
        )
        returned = result.get("records", [])
        if not returned or not returned[0].get("record_id"):
            raise ValueError("表格写入未返回记录标识，不能确认成功")
        remote[:] = [r for r in remote if r.get("record_id") != returned[0]["record_id"]] + returned
        with self.store.db:
            self.store.db.execute(
                "INSERT INTO cloud_sync VALUES(?,?) ON CONFLICT(entity) DO UPDATE SET digest=excluded.digest",
                (entity, digest),
            )
        self.status["writes"] += 1

    async def sync_once(self):
        remote = {title: await self.records(title) for title in ("作品", "版本", "值班", "反馈")}
        # 只回流工作人员维护的别名，不用表格旧版本覆盖新的本地提交结果。
        with self.store.db:
            for row in remote["作品"]:
                values = row.get("values", {})
                work_id = plain(values.get("作品ID", ""))
                if self.store.get(work_id):
                    self.store.db.execute(
                        "UPDATE works SET aliases=? WHERE id=?", (plain(values.get("别名", "")), work_id)
                    )
        for work in self.store.works():
            await self.upsert(
                "作品",
                "作品ID",
                work["id"],
                {
                    "作品ID": work["id"],
                    "作品名": work["title"],
                    "队名": work["team"],
                    "成员": work["members"],
                    "别名": work["aliases"],
                    "简介": work["description"],
                    "最新版本": work["latest"],
                    "状态": work["status"],
                },
                remote["作品"],
            )
            for item in self.store.versions(work["id"]):
                await self.upsert(
                    "版本",
                    "tag",
                    item["tag"],
                    {
                        "作品ID": work["id"],
                        "版本号": item["version"],
                        "commit SHA": item["commit_sha"],
                        "tag": item["tag"],
                        "提交时间": cloud_time(item["submitted_at"]),
                        "来源": "本地演练 files",
                        "内容哈希": item["content_hash"],
                        "检查结果": json.dumps(item["checks"], ensure_ascii=False),
                        "说明": item["description"],
                    },
                    remote["版本"],
                )
        # 值班无独立业务编号，以事项+起止时段组合去重，不覆盖已有人员记录。
        for row in self.store.db.execute("SELECT * FROM duty").fetchall():
            start, end = cloud_time(row["start"]), cloud_time(row["end"])
            exists = any(
                plain(r.get("values", {}).get("事项类别")) == row["category"]
                and plain(r.get("values", {}).get("负责人 userid")) == row["userid"]
                for r in remote["值班"]
            )
            if not exists:
                await self.call(
                    "smartsheet",
                    "records",
                    "add",
                    payload={
                        "docid": self.docid,
                        "sheet_title": "值班",
                        "records": [
                            {
                                "values": {
                                    "开始时间": start,
                                    "结束时间": end,
                                    "事项类别": row["category"],
                                    "负责人姓名": row["name"],
                                    "负责人 userid": row["userid"],
                                }
                            }
                        ],
                    },
                )
        for row in self.store.db.execute("SELECT * FROM feedback").fetchall():
            await self.upsert(
                "反馈",
                "feedback_id",
                row["id"],
                {
                    "时间": cloud_time(row["time"]),
                    "提问人 userid": row["userid"],
                    "角色": row["role"],
                    "问题": row["question"],
                    "机器人回答": row["answer"],
                    "使用的工具": row["tools"],
                    "是否转人工": bool(row["escalated"]),
                    "转给谁": row["assignee"],
                    "评价": row["rating"],
                    "feedback_id": row["id"],
                },
                remote["反馈"],
            )
        self.status.update(state="ready", last_sync=now_iso(), error=None)

    async def run(self, interval: float = 60):
        while True:
            try:
                await self.sync_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.status.update(
                    state="failed", error=exc.code if isinstance(exc, WecomError) else type(exc).__name__
                )
            await asyncio.sleep(interval)

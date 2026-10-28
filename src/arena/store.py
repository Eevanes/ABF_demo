import hashlib
import json
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


class Store:
    """本地登记表。只向业务层返回不含密钥哈希的数据。"""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS works (
          id TEXT PRIMARY KEY, title TEXT, team TEXT UNIQUE, members TEXT, aliases TEXT,
          description TEXT DEFAULT '', latest INTEGER DEFAULT 0, key_hash TEXT UNIQUE,
          status TEXT DEFAULT '已报名');
        CREATE TABLE IF NOT EXISTS versions (
          work_id TEXT, version INTEGER, commit_sha TEXT, tag TEXT, submitted_at TEXT,
          description TEXT, content_hash TEXT, checks TEXT,
          PRIMARY KEY(work_id, version));
        CREATE TABLE IF NOT EXISTS duty (
          start TEXT, end TEXT, category TEXT, name TEXT, userid TEXT);
        CREATE TABLE IF NOT EXISTS feedback (
          id TEXT PRIMARY KEY, time TEXT, userid TEXT, role TEXT, question TEXT,
          answer TEXT, tools TEXT, escalated INTEGER, assignee TEXT, rating TEXT DEFAULT '');
        """)

    @staticmethod
    def public(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {k: row[k] for k in row.keys() if k != "key_hash"}

    def works(self) -> list[dict[str, Any]]:
        return [self.public(r) for r in self.db.execute("SELECT * FROM works ORDER BY id")]  # type: ignore[misc]

    def get(self, work_id: str) -> dict[str, Any] | None:
        return self.public(self.db.execute("SELECT * FROM works WHERE id=?", (work_id,)).fetchone())

    def require(self, work_id: str) -> dict[str, Any]:
        work = self.get(work_id)
        if work is None:
            raise ValueError("找不到该作品")
        return work

    def bind_key(self, work_id: str, key: str) -> None:
        self.require(work_id)
        if not key.startswith("hk_") or len(key) < 35:
            raise ValueError("队伍密钥须以 hk_ 开头，长度至少 35")
        with self.db:
            self.db.execute("UPDATE works SET key_hash=? WHERE id=?", (hash_key(key), work_id))

    def authenticate(self, key: str) -> dict[str, Any] | None:
        row = self.db.execute(
            "SELECT * FROM works WHERE key_hash=? AND status!='已禁用'", (hash_key(key),)
        ).fetchone()
        return self.public(row)

    def register(self, team: str, title: str, members: str = "") -> tuple[dict[str, Any], str | None]:
        if not team.strip():
            raise ValueError("队名不能为空")
        with self.db:
            old = self.db.execute("SELECT * FROM works WHERE team=?", (team,)).fetchone()
            if old:
                return self.public(old), None  # type: ignore[return-value]
            n = self.db.execute("SELECT COALESCE(MAX(CAST(substr(id,3) AS INT)),0)+1 FROM works").fetchone()[
                0
            ]
            work_id = f"H-{n:03d}"
            key = "hk_" + secrets.token_urlsafe(32)
            self.db.execute(
                "INSERT INTO works(id,title,team,members,aliases,key_hash) VALUES(?,?,?,?,?,?)",
                (work_id, title, team, members, "", hash_key(key)),
            )
        return self.get(work_id), key  # type: ignore[return-value]

    def reset_key(self, work_id: str) -> str:
        if not self.get(work_id):
            raise ValueError("没有该作品")
        key = "hk_" + secrets.token_urlsafe(32)
        with self.db:
            self.db.execute("UPDATE works SET key_hash=? WHERE id=?", (hash_key(key), work_id))
        return key

    def set_status(self, work_id: str, disabled: bool) -> None:
        with self.db:
            self.db.execute(
                "UPDATE works SET status=? WHERE id=?", ("已禁用" if disabled else "已报名", work_id)
            )

    def versions(self, work_id: str) -> list[dict[str, Any]]:
        rows = self.db.execute("SELECT * FROM versions WHERE work_id=? ORDER BY version", (work_id,))
        return [dict(r) | {"checks": json.loads(r["checks"])} for r in rows]

    def record_submission(self, work_id: str, title: str | None, item: dict[str, Any]) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO versions VALUES(?,?,?,?,?,?,?,?)",
                (
                    work_id,
                    item["version"],
                    item["commit_sha"],
                    item["tag"],
                    item["submitted_at"],
                    item["description"],
                    item["content_hash"],
                    json.dumps(item["checks"], ensure_ascii=False),
                ),
            )
            self.db.execute(
                "UPDATE works SET latest=?,description=?,title=COALESCE(?,title),status='已提交' WHERE id=?",
                (item["version"], item["description"], title, work_id),
            )

    def add_duty(self, start: str, end: str, category: str, name: str, userid: str) -> None:
        with self.db:
            self.db.execute("INSERT INTO duty VALUES(?,?,?,?,?)", (start, end, category, name, userid))

    def on_duty(self, category: str) -> dict[str, Any] | None:
        current = datetime.now(timezone.utc)
        for row in self.db.execute("SELECT * FROM duty WHERE category=? ORDER BY start", (category,)):
            if datetime.fromisoformat(row["start"]) <= current < datetime.fromisoformat(row["end"]):
                return dict(row)
        return None

    def feedback(self, item: dict[str, Any]) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO feedback(id,time,userid,role,question,answer,tools,escalated,assignee) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    item["id"],
                    now_iso(),
                    item["userid"],
                    item["role"],
                    item["question"],
                    item["answer"],
                    json.dumps(item["tools"], ensure_ascii=False),
                    item["escalated"],
                    item.get("assignee", ""),
                ),
            )

    def rate(self, feedback_id: str, userid: str, rating: str) -> None:
        if rating not in ("赞", "踩"):
            raise ValueError("评价只能为赞或踩")
        with self.db:
            cursor = self.db.execute(
                "UPDATE feedback SET rating=? WHERE id=? AND userid=?", (rating, feedback_id, userid)
            )
            if not cursor.rowcount:
                raise ValueError("找不到本人对应的反馈")

    def feedback_report(self) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in self.db.execute("SELECT * FROM feedback WHERE rating='踩' OR escalated=1 ORDER BY time")
        ]

    def close(self) -> None:
        self.db.close()

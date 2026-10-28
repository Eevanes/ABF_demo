"""Durable operation journal; not a second business registry and never stores credentials."""

import json
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path


class OperationJournal:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS submissions (
                submission_id TEXT PRIMARY KEY, work_id TEXT NOT NULL,
                fingerprint TEXT NOT NULL, state TEXT NOT NULL, payload TEXT NOT NULL)""")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path)
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, submission_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT work_id,fingerprint,state,payload FROM submissions WHERE submission_id=?",
                (submission_id,),
            ).fetchone()
        return dict(zip(("work_id", "fingerprint", "state", "payload"), (*row[:3], json.loads(row[3])))) if row else None

    def save(self, submission_id: str, work_id: str, fingerprint: str, state: str, payload: dict):
        with self.connect() as db:
            db.execute(
                "INSERT INTO submissions VALUES(?,?,?,?,?) ON CONFLICT(submission_id) DO UPDATE SET state=excluded.state,payload=excluded.payload",
                (submission_id, work_id, fingerprint, state, json.dumps(payload, ensure_ascii=False)),
            )

    def pending(self, work_id: str | None = None) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT submission_id FROM submissions WHERE state!='registered'" + (" AND work_id=?" if work_id else ""),
                (work_id,) if work_id else (),
            ).fetchall()
        return [self.get(row[0]) | {"submission_id": row[0]} for row in rows]  # type: ignore[operator]

    @contextmanager
    def exclusive(self):
        """Fail fast if a second process uses the same managed submission directory."""
        with self.path.with_suffix(".lock").open("a+b") as handle:
            handle.seek(0, 2)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                if sys.platform == "win32":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise RuntimeError("另一个 Arena 实例正在写入，请使用单实例部署") from None
            try:
                yield
            finally:
                handle.seek(0)
                if sys.platform == "win32":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

"""Frozen, published policy snapshot loaded from a Git-managed release package."""

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

import jieba
import yaml

from arena.staff_auth import StaffIdentity


class PolicyService:
    def __init__(self, root: Path, at: datetime | None = None):
        self.snapshot_at = at or datetime.now(timezone.utc)
        if self.snapshot_at.tzinfo is None:
            raise ValueError("规则快照时间必须带时区")
        published: dict[str, tuple[datetime, dict]] = {}
        self.draft_count = 0
        for path in sorted(root.rglob("*.md")):
            raw = path.read_text(encoding="utf-8")
            parts = raw.split("---", 2)
            if len(parts) != 3 or parts[0].strip():
                self.draft_count += 1
                continue
            meta = yaml.safe_load(parts[1])
            if not isinstance(meta, dict) or meta.get("status") != "published":
                self.draft_count += 1
                continue
            required = ("policy_id", "version", "effective_at", "approved_by", "source_url", "content_hash", "allowed_roles")
            if any(not meta.get(key) for key in required):
                raise ValueError(f"已发布规则缺少审批或版本元数据: {path.name}")
            roles = meta["allowed_roles"]
            if not isinstance(roles, list) or not set(roles) <= {"public", "staff", "admin"}:
                raise ValueError(f"规则权限无效: {path.name}")
            if "sop" in path.relative_to(root).parts and "public" in roles:
                raise ValueError(f"内部 SOP 不得发布为公开规则: {path.name}")
            effective = datetime.fromisoformat(str(meta["effective_at"]))
            if effective.tzinfo is None:
                raise ValueError(f"规则生效时间必须带时区: {path.name}")
            body = parts[2].strip()
            digest = hashlib.sha256(body.encode()).hexdigest()
            if digest != meta["content_hash"]:
                raise ValueError(f"规则内容哈希不匹配: {path.name}")
            if effective > self.snapshot_at:
                continue
            item = {key: str(meta[key]) for key in required if key != "allowed_roles"} | {
                "allowed_roles": roles, "text": body,
                "source": path.relative_to(root).as_posix(),
            }
            policy_id = str(meta["policy_id"])
            old = published.get(policy_id)
            if old and old[0] == effective:
                raise ValueError(f"同一规则生效版本冲突: {policy_id}")
            if old is None or effective > old[0]:
                published[policy_id] = (effective, item)
        self._policies = [item for _, item in published.values()]

    def search(self, query: str, identity: StaffIdentity, internal: bool = False) -> list[dict]:
        if internal:
            identity.require_staff()
        terms = {term.lower() for term in jieba.cut(query[:500]) if re.search(r"[\w\u4e00-\u9fff]", term)}
        if not terms:
            return []
        ranked = []
        for item in self._policies:
            public = "public" in item["allowed_roles"]
            if internal:
                allowed = identity.role in item["allowed_roles"] and not public
            else:
                allowed = public
            if not allowed:
                continue
            text = item["text"].lower()
            score = sum(term in text for term in terms)
            if score:
                ranked.append((score, item))
        return [dict(item) for _, item in sorted(ranked, key=lambda pair: -pair[0])[:3]]

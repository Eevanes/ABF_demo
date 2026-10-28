import hashlib
from datetime import datetime, timezone

import pytest
import yaml

from arena.services.policy import PolicyService
from arena.staff_auth import StaffIdentity


def publish(path, text="提交作品必须包含 README。", **overrides):
    meta = {
        "policy_id": "submission", "version": "1.0.0", "status": "published",
        "effective_at": "2026-01-01T00:00:00+00:00", "approved_by": "test-reviewer",
        "source_url": "https://example.invalid/policy/submission", "allowed_roles": ["public"],
        "content_hash": hashlib.sha256(text.encode()).hexdigest(),
    } | overrides
    path.write_text("---\n" + yaml.safe_dump(meta, allow_unicode=True) + "---\n" + text, encoding="utf-8")


def test_published_only_role_filter_and_frozen_snapshot(tmp_path):
    publish(tmp_path / "public.md")
    publish(tmp_path / "staff.md", "签到需核对内部清单。", policy_id="checkin", allowed_roles=["staff", "admin"])
    publish(tmp_path / "future.md", "提交新规则", version="2.0.0", effective_at="2027-01-01T00:00:00+00:00")
    (tmp_path / "draft.md").write_text("提交草稿不可用于答复", encoding="utf-8")
    policy = PolicyService(tmp_path, at=datetime(2026, 10, 28, tzinfo=timezone.utc))
    public = StaffIdentity("")
    items = policy.search("提交", public)
    assert len(items) == 1 and items[0]["version"] == "1.0.0"
    assert items[0]["content_hash"] and items[0]["source_url"]
    assert policy.draft_count == 1
    assert not policy.search("签到", public)
    with pytest.raises(PermissionError):
        policy.search("签到", public, internal=True)
    assert policy.search("签到", StaffIdentity("staff", "staff"), internal=True)
    publish(tmp_path / "public.md", "规则已修改但旧快照不可变", version="3.0.0")
    assert policy.search("提交", public)[0]["version"] == "1.0.0"


def test_policy_tamper_and_conflicting_versions_fail_closed(tmp_path):
    publish(tmp_path / "bad.md", content_hash="wrong")
    with pytest.raises(ValueError, match="哈希"):
        PolicyService(tmp_path)
    publish(tmp_path / "bad.md")
    publish(tmp_path / "conflict.md", "提交冲突规则")
    with pytest.raises(ValueError, match="冲突"):
        PolicyService(tmp_path)


@pytest.mark.parametrize("field,value", [("approved_by", ""), ("allowed_roles", ["participant"]), ("effective_at", "2026-01-01")])
def test_invalid_release_metadata_rejected(tmp_path, field, value):
    publish(tmp_path / "bad.md", **{field: value})
    with pytest.raises(ValueError):
        PolicyService(tmp_path)

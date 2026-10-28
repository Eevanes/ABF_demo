import asyncio
import inspect
from typing import Any

from rapidfuzz.fuzz import WRatio

from arena.staff_auth import StaffIdentity


async def registry_call(registry: Any, name: str, *args: Any) -> Any:
    method = getattr(registry, name)
    if inspect.iscoroutinefunction(method):
        return await method(*args)
    result = await asyncio.to_thread(method, *args)
    return await result if inspect.isawaitable(result) else result


class QueryService:
    """Shared query rules; both MCP and the legacy harness call this service."""

    def __init__(self, registry: Any):
        self.registry = registry

    async def search_works(self, query: str, identity: StaffIdentity, sources: bool = True) -> list[dict]:
        query = query.strip().lower()[:500]
        if not query:
            return []
        staff = identity.role in {"staff", "admin"}
        results = []
        for work in await registry_call(self.registry, "works"):
            if work["status"] == "已禁用":
                continue
            if staff and identity.work_ids is not None and work["id"] not in identity.work_ids:
                continue
            keys = ("id", "title", "team", "members", "aliases", "description") if staff else ("id", "title", "team")
            fields = [str(work.get(key, "")) for key in keys]
            score = max(WRatio(query, value.lower()) for value in fields)
            if any(query in value.lower() for value in fields):
                score = 100
            if score < 45:
                continue
            allowed = ("id", "title", "team", "latest") if staff else ("id", "title", "team")
            item = {key: work[key] for key in allowed} | {"score": score}
            if sources:
                item["source"] = {"kind": "registry", "work_id": work["id"]}
            results.append(item)
        return sorted(results, key=lambda work: (-work["score"], work["id"]))[:5]

    async def get_work(self, work_id: str, identity: StaffIdentity) -> dict | None:
        identity.require_staff(work_id)
        found = await registry_call(self.registry, "get", work_id)
        if not found:
            return None
        # Projection prevents a new registry field accidentally exposing credentials.
        safe = {key: found[key] for key in (
            "id", "title", "team", "members", "aliases", "description", "latest", "status"
        ) if key in found}
        return safe | {"versions": await self.list_versions(work_id, identity)}

    async def list_versions(self, work_id: str, identity: StaffIdentity) -> list[dict]:
        identity.require_staff(work_id)
        return [
            {key: item[key] for key in (
                "work_id", "version", "commit_sha", "tag", "submitted_at", "description",
                "content_hash", "checks", "repo_link", "submission_id", "policy_version"
            ) if key in item}
            for item in await registry_call(self.registry, "versions", work_id)
        ]

    async def get_on_duty(self, category: str, identity: StaffIdentity) -> dict | None:
        identity.require_staff()
        return await registry_call(self.registry, "on_duty", category)

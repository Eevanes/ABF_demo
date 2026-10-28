"""Explicit backend selection; legacy mirrors cannot run with the cloud Registry."""

import hashlib
import hmac
import json
import os
import re

from arena.config import Settings
from arena.ports.registry import Registry
from arena.ports.writer import ArtifactWriter
from arena.store import Store
from arena.writer import LocalGitWriter


class EnvironmentCredentials:
    """A small independent credential authority, with no mirrored business records."""

    def authenticate(self, key: str) -> dict | None:
        mappings = json.loads(os.environ.get("ARENA_TEAM_CREDENTIALS", "{}"))
        if not isinstance(mappings, dict):
            raise ValueError("ARENA_TEAM_CREDENTIALS must map work IDs to SHA256 hashes")
        digest = hashlib.sha256(key.encode()).hexdigest()
        for work_id, expected in mappings.items():
            if not re.fullmatch(r"H-[0-9]{3,}", work_id) or not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected):
                raise ValueError("invalid team credential mapping")
            if hmac.compare_digest(digest, expected):
                return {"id": work_id}
        return None

    def bind_key(self, work_id: str, key: str) -> None:
        raise PermissionError("Update ARENA_TEAM_CREDENTIALS in the trusted local environment and restart")


def registry_backend(settings: Settings) -> Registry:
    registry_mode = os.environ.get("ARENA_REGISTRY", "local")
    if registry_mode not in ("local", "smartsheet"):
        raise ValueError("unsupported Arena backend")
    if registry_mode == "smartsheet":
        from arena.adapters.smartsheet_registry import SmartSheetRegistry

        cloud_registry = SmartSheetRegistry(EnvironmentCredentials(),
            write_enabled=os.environ.get("ARENA_SMARTSHEET_WRITES_ENABLED", "").lower() == "true")
        if cloud_registry.write_enabled:
            cloud_registry.verify_schema()
        return cloud_registry
    else:
        return Store(settings.data_dir / "registry.sqlite3")


def backends(settings: Settings) -> tuple[Registry, ArtifactWriter]:
    writer_mode = os.environ.get("ARENA_WRITER", "local")
    if writer_mode not in ("local", "github"):
        raise ValueError("unsupported Arena backend")
    registry = registry_backend(settings)
    if writer_mode == "github":
        from arena.adapters.github_app_writer import GitHubAppWriter

        writer: ArtifactWriter = GitHubAppWriter.from_environment()
    else:
        writer = LocalGitWriter(settings.data_dir / "works-repo")
    return registry, writer

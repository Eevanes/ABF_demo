"""Read-only v0.4 configuration diagnostics, separate from external acceptance."""

import ipaddress
import json
import os
import re
from urllib.parse import urlsplit

from arena.runtime import EnvironmentCredentials
from arena.staff_auth import StaffAuth

GITHUB_VARIABLES = (
    "GITHUB_APP_ID", "GITHUB_INSTALLATION_ID", "GITHUB_APP_PRIVATE_KEY", "GITHUB_REPO",
)


def public_https(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        if (parsed.scheme != "https" or not host or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment
                or host.rstrip(".").lower() == "localhost"):
            return False
        # DNS reachability and certificate validity require a separate live probe.
        _ = parsed.port
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return bool(re.fullmatch(r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
                r"[A-Za-z](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", host))
    except ValueError:
        return False


def configuration_report() -> dict:
    configured = {name: bool(os.environ.get(name)) for name in (*GITHUB_VARIABLES,
        "PUBLIC_BASE_URL", "SMARTSHEET_DOCID", "ARENA_V04_SMARTSHEET_DOCID",
        "ARENA_TEAM_CREDENTIALS", "ARENA_STAFF_CREDENTIALS")}
    errors = []
    try:
        EnvironmentCredentials().authenticate("configuration-probe-not-a-credential")
    except (ValueError, TypeError):
        errors.append("invalid_team_credentials")
    try:
        StaffAuth()
    except ValueError:
        errors.append("invalid_staff_credentials")
    sandbox = os.environ.get("ARENA_V04_SMARTSHEET_DOCID", "")
    isolated = bool(sandbox) and sandbox != os.environ.get("SMARTSHEET_DOCID", "")
    github = all(configured[name] for name in GITHUB_VARIABLES)
    # These are configuration facts, never assertions that a channel works.
    return {
        "mode": "configuration_only", "configured": configured,
        "configuration_errors": errors,
        "submission": {
            "github_app_configured": github,
            "github_e2e": "not_verified",
            "sandbox_is_separate": isolated,
            "registry": os.environ.get("ARENA_REGISTRY", "local"),
            "writer": os.environ.get("ARENA_WRITER", "local"),
        },
        "remote_access": {
            "https_url_syntax_valid": public_https(os.environ.get("PUBLIC_BASE_URL", "")),
            "tls_and_remote_client": "not_verified",
        },
        "staff": {
            "route": "compatibility_mcp",
            "native_knowledge_in_wecom": "not_verified",
            "native_sheets_in_wecom": "not_verified",
            "two_user_isolation": "not_verified",
            "trusted_sender": "not_verified",
            "writes_enabled": os.environ.get("ARENA_STAFF_WRITES_ENABLED", "").lower() == "true",
            "notification_provider": "not_attached",
        },
        "production_cutover": False,
    }


def probe_smartsheet(report: dict) -> None:
    """Read the dedicated v0.4 sandbox only; never default to operational tables."""
    from arena.adapters.smartsheet_registry import RegistryError, SmartSheetRegistry
    from arena.wecom_cli import WecomError

    if not report["submission"]["sandbox_is_separate"]:
        report["smartsheet"] = {"state": "not_run", "code": "separate_v04_sandbox_required"}
        return
    registry = None
    try:
        registry = SmartSheetRegistry(EnvironmentCredentials(),
            docid=os.environ["ARENA_V04_SMARTSHEET_DOCID"])
        schema = registry.verify_schema()
        report["smartsheet"] = {"state": "live_read_passed",
            "sheets": len(schema["sheets"]), "works_count": len(registry.works()), "writes": False}
    except (RegistryError, WecomError) as exc:
        # Only known machine codes are printable; remote messages can contain IDs.
        report["smartsheet"] = {"state": "failed", "error_type": type(exc).__name__, "code": str(exc.code)}
    except Exception as exc:
        report["smartsheet"] = {"state": "failed", "error_type": type(exc).__name__}
    finally:
        if registry is not None:
            registry.close()


def report_json(live_read: bool = False) -> str:
    report = configuration_report()
    if live_read:
        report["mode"] = "live_read_only"
        probe_smartsheet(report)
    return json.dumps(report, ensure_ascii=False, indent=2)

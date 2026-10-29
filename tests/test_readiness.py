import json

import pytest

from arena.readiness import configuration_report, probe_smartsheet, public_https


@pytest.mark.parametrize("url", ["http://example.com/mcp", "https://localhost/mcp",
    "https://127.0.0.1/mcp", "https://[::1]/mcp", "https://10.0.0.1/mcp",
    "https://user:password@example.com/mcp", "https://example.com/mcp?token=hidden",
    "https://example.com:invalid/mcp", "https:///mcp"])
def test_remote_url_rejects_local_or_embedded_credentials(url):
    assert not public_https(url)


def test_configuration_never_certifies_external_acceptance_or_echoes_values(monkeypatch):
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "synthetic-private-value-do-not-print")
    monkeypatch.setenv("ARENA_TEAM_CREDENTIALS", "[]")
    monkeypatch.setenv("SMARTSHEET_DOCID", "synthetic-operational-table")
    monkeypatch.setenv("ARENA_V04_SMARTSHEET_DOCID", "synthetic-operational-table")
    report = configuration_report()
    assert report["production_cutover"] is False
    assert report["submission"]["github_e2e"] == "not_verified"
    assert "invalid_team_credentials" in report["configuration_errors"]
    assert "synthetic-private" not in json.dumps(report)
    assert "synthetic-operational" not in json.dumps(report)
    probe_smartsheet(report)
    assert report["smartsheet"]["code"] == "separate_v04_sandbox_required"
    assert public_https("https://arena.example.com/mcp")

import httpx

from arena.mcp_app import create_app
from arena.walkthrough import walkthrough


async def test_real_http_mcp(tmp_path):
    result = await walkthrough(tmp_path)
    assert result["team_isolation_passed"]
    assert result["invalid_key_status"] == 401


async def test_body_limit_and_health(bundle):
    settings, store, _, _ = bundle
    settings.max_inline_bytes = 10
    _, key = store.register("体积测试", "作品")
    transport = httpx.ASGITransport(app=create_app(settings, store))
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        assert (await client.get("/healthz")).json()["mode"] == "local-demo"
        response = await client.post(
            "/mcp", content=b"x" * (1024 * 1024 + 21), headers={"Authorization": "Bearer " + key}
        )
        assert response.status_code == 413

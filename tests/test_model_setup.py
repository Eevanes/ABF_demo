import httpx
import respx

from arena.model_setup import create_model_app


async def test_model_setup_rejects_cross_origin():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_model_app(save=lambda value: None)),
        base_url="http://127.0.0.1",
    ) as client:
        r = await client.post(
            "/configure", json={"api_key": "dummy"}, headers={"Origin": "https://foreign.example"}
        )
        assert r.status_code == 403


@respx.mock
async def test_model_key_saved_only_after_real_tool_response():
    saved = []
    respx.post("https://api.deepseek.com/chat/completions").respond(
        200, json={"choices": [{"message": {"tool_calls": [{"function": {"name": "arena_ping"}}]}}]}
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_model_app(save=saved.append)), base_url="http://127.0.0.1"
    ) as client:
        r = await client.post("/configure", json={"api_key": "dummy"}, headers={"Origin": "http://127.0.0.1"})
        assert r.json()["state"] == "configured"
        assert saved == ["dummy"]
        assert "dummy" not in r.text


@respx.mock
async def test_failed_model_request_does_not_save_key():
    saved = []
    respx.post("https://api.deepseek.com/chat/completions").respond(401)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_model_app(save=saved.append)), base_url="http://127.0.0.1"
    ) as client:
        r = await client.post("/configure", json={"api_key": "dummy"}, headers={"Origin": "http://127.0.0.1"})
        assert r.status_code == 400
        assert not saved

import httpx
import respx

from arena.wecom_auth import TOKEN_ENDPOINT, AuthFlow, create_auth_app


@respx.mock
async def test_bootstrap_keeps_credentials_out_of_status():
    route = respx.post(TOKEN_ENDPOINT).respond(200, json={"errcode": 0, "token": "dummy-token"})
    flow = AuthFlow(save=lambda values: None)
    async with httpx.AsyncClient() as client:
        values = await flow.bootstrap(client, {"botid": "dummy-bot", "secret": "dummy-secret"})
    assert values["WECOM_CLI_ACCESS_TOKEN"] == "dummy-token"
    assert b"dummy-secret" not in route.calls[0].request.content
    assert "dummy-token" not in str(flow.status())
    assert "dummy-secret" not in str(flow.status())


async def test_auth_page_rejects_foreign_host():
    transport = httpx.ASGITransport(app=create_auth_app(AuthFlow()))
    async with httpx.AsyncClient(transport=transport, base_url="http://foreign.example") as client:
        assert (await client.get("/")).status_code == 403
        assert (await client.get("/status")).status_code == 403

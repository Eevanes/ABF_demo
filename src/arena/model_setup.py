"""Loopback-only DeepSeek credential intake. The user types the key, never the agent."""

import os
import sys

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route


def save_model_key(value: str) -> None:
    if sys.platform != "win32":
        raise ValueError("此安装器仅支持 Windows 用户环境变量")
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
        winreg.SetValueEx(key, "DEEPSEEK_API_KEY", 0, winreg.REG_SZ, value)
    os.environ["DEEPSEEK_API_KEY"] = value


def create_model_app(save=save_model_key):
    state = {"state": "waiting_for_user", "live_model_test": "not_run"}

    def allowed(request: Request) -> bool:
        return request.url.hostname in ("127.0.0.1", "localhost")

    async def home(request: Request):
        if not allowed(request):
            return HTMLResponse("Forbidden", status_code=403)
        return HTMLResponse(
            """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>Arena · DeepSeek 接入</title>
<style>body{font:18px system-ui;background:#f5f5f4;max-width:620px;margin:64px auto;color:#292524}form{background:white;padding:28px;border-radius:16px}input{width:95%;padding:12px;font-size:18px}button{margin-top:20px;padding:12px;background:#d86d2d;color:white;border:0;border-radius:6px;font-size:18px}</style>
<h1>Arena · DeepSeek 接入</h1><p>企业微信身份与测试表格已就绪。请在本机输入 DeepSeek API Key，勿发到聊天。</p>
<p>没有 Key？可前往 <a href="https://platform.deepseek.com/api_keys" target="_blank" rel="noreferrer">DeepSeek 控制台</a> 创建。</p>
<form id="setup" autocomplete="off"><label>API Key<input type="password" id="key" autocomplete="off" required></label>
<p>点击后只向 api.deepseek.com 验证模型与工具调用能力，随后保存到本机用户环境变量。不会写入项目文件。</p>
<button type="submit">验证并保存到本机环境变量</button><p id="status"></p></form>
<script>document.getElementById('setup').onsubmit=async e=>{e.preventDefault();let input=document.getElementById('key');let key=input.value;input.value='';document.getElementById('status').textContent='正在验证…';let r=await fetch('/configure',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({api_key:key})});key='';let s=await r.json();document.getElementById('status').textContent=s.state+(s.code?'：'+s.code:'');}</script></html>""",
            headers={
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "X-Frame-Options": "DENY",
            },
        )

    async def configure(request: Request):
        if (
            not allowed(request)
            or request.headers.get("origin") != f"{request.url.scheme}://{request.url.netloc}"
        ):
            return JSONResponse({"state": "forbidden"}, status_code=403)
        raw = await request.body()
        if len(raw) > 4096:
            return JSONResponse({"state": "input_too_large"}, status_code=413)
        try:
            key = (await request.json()).get("api_key", "").strip()
            if not isinstance(key, str) or not key or len(key) > 1000:
                return JSONResponse({"state": "invalid_key_input"}, status_code=400)
            model = os.environ.get("LLM_MODEL", "deepseek-flash")
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                response = await client.post(
                    "https://api.deepseek.com/chat/completions",
                    headers={"Authorization": "Bearer " + key},
                    json={
                        "model": model,
                        "messages": [
                            {"role": "user", "content": "Connection test. Call arena_ping with status ready."}
                        ],
                        "tools": [
                            {
                                "type": "function",
                                "function": {
                                    "name": "arena_ping",
                                    "description": "Verify connection only. No side effects.",
                                    "parameters": {
                                        "type": "object",
                                        "properties": {"status": {"type": "string"}},
                                        "required": ["status"],
                                    },
                                },
                            }
                        ],
                        "thinking": {"type": "disabled"},
                        "max_tokens": 100,
                    },
                )
                if response.status_code != 200:
                    return JSONResponse(
                        {"state": "provider_request_failed", "code": response.status_code}, status_code=400
                    )
                calls = response.json()["choices"][0]["message"].get("tool_calls", [])
                if not any(call.get("function", {}).get("name") == "arena_ping" for call in calls):
                    return JSONResponse({"state": "tool_call_not_verified"}, status_code=400)
            save(key)
            state.update(state="configured", live_model_test="tool_call_passed", model=model)
            return JSONResponse(state, headers={"Cache-Control": "no-store"})
        except Exception:
            return JSONResponse({"state": "connection_or_input_error"}, status_code=400)

    async def status(request: Request):
        return (
            JSONResponse(state, headers={"Cache-Control": "no-store"})
            if allowed(request)
            else JSONResponse({}, status_code=403)
        )

    return Starlette(
        routes=[Route("/", home), Route("/configure", configure, methods=["POST"]), Route("/status", status)]
    )

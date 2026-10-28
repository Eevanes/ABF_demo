"""官方 CLI 认证协议的环境变量适配器，不读取或写入 credentials.enc。

协议来源：WecomTeam/wecom-cli 的 auth/qrcode.rs 和 auth/bootstrap.rs。
"""

import asyncio
import hashlib
import io
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from typing import Callable

import httpx
import qrcode
import qrcode.image.svg
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

QR_GENERATE = "https://work.weixin.qq.com/ai/qc/generate"
QR_QUERY = "https://work.weixin.qq.com/ai/qc/query_result"
TOKEN_ENDPOINT = "https://qyapi.weixin.qq.com/cgi-bin/aibot/cli/get_cli_config"
SECRET_NAMES = ("WECOM_BOT_ID", "WECOM_BOT_SECRET", "WECOM_CLI_ACCESS_TOKEN")


def save_user_environment(values: dict[str, str]) -> None:
    if sys.platform != "win32":
        raise ValueError("此环境变量安装器目前只支持 Windows")
    import winreg

    if set(values) != set(SECRET_NAMES) or not all(values.values()):
        raise ValueError("认证材料不完整")
    # 写 Windows 用户环境变量，不生成明文或加密凭据文件。
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
        for name, value in values.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
            os.environ[name] = value


def import_user_environment(names: tuple[str, ...] = SECRET_NAMES) -> None:
    """供 CLI 子进程启动时显式调用；不覆盖已有进程级配置。"""
    if sys.platform != "win32":
        return
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            for name in names:
                if os.environ.get(name):
                    continue
                try:
                    value, _ = winreg.QueryValueEx(key, name)
                except FileNotFoundError:
                    continue
                if isinstance(value, str) and value:
                    os.environ[name] = value
    except FileNotFoundError:
        return


async def cli_identity(values: dict[str, str]) -> dict:
    command = shutil.which("wecom-cli")
    if not command:
        return {"ok": False, "code": "cli_missing"}
    result = await asyncio.to_thread(
        subprocess.run,
        [command, "identity", "whoami"],
        env=os.environ | values,
        capture_output=True,
        timeout=25,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        data = json.loads(result.stdout)
    except ValueError:
        return {"ok": False, "code": "unreadable_identity_response"}
    if "error" in data:
        return {"ok": False, "code": data["error"].get("code")}
    return {"ok": result.returncode == 0}


class AuthFlow:
    def __init__(self, save: Callable = save_user_environment, verify: Callable = cli_identity):
        self.state = "initializing"
        self.error: str | int | None = None
        self.svg = ""
        self.scode = ""
        self.save, self.verify = save, verify
        self.identity: dict = {}

    async def bootstrap(self, client: httpx.AsyncClient, bot: dict) -> dict[str, str]:
        bot_id, secret = bot.get("botid", ""), bot.get("secret", "")
        if not bot_id or not secret:
            raise ValueError("扫码未返回完整机器人信息")
        stamp = int(time.time())
        nonce = f"cli_{int(time.time() * 1000)}_{secrets.token_hex(4)}"
        signature = hashlib.sha256(f"{secret}{bot_id}{stamp}{nonce}".encode()).hexdigest()
        response = await client.post(
            TOKEN_ENDPOINT,
            json={
                "bot_id": bot_id,
                "time": stamp,
                "nonce": nonce,
                "signature": signature,
                "bind_source": 2,
            },
        )
        response.raise_for_status()
        data = response.json()
        if data.get("errcode", 0) != 0 or not data.get("token"):
            self.error = data.get("errcode", "missing_token")
            raise ValueError("换取 CLI token 未成功")
        return {"WECOM_BOT_ID": bot_id, "WECOM_BOT_SECRET": secret, "WECOM_CLI_ACCESS_TOKEN": data["token"]}

    async def run(self):
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
                response = await client.get(QR_GENERATE, params={"source": "wecom_cli_external", "plat": 2})
                response.raise_for_status()
                data = response.json().get("data") or {}
                self.scode = data.get("scode", "")
                auth_url = data.get("auth_url", "")
                if not self.scode or not auth_url:
                    raise ValueError("官方接口未返回扫码会话")
                # 只在内存中生成 SVG，扫码会话码与机器人凭据均不落盘。
                image = qrcode.make(auth_url, image_factory=qrcode.image.svg.SvgPathImage)
                buffer = io.BytesIO()
                image.save(buffer)
                self.svg = buffer.getvalue().decode()
                self.state = "waiting_scan"
                deadline = time.monotonic() + 300
                while time.monotonic() < deadline:
                    response = await client.get(QR_QUERY, params={"scode": self.scode})
                    response.raise_for_status()
                    result = response.json().get("data") or {}
                    if result.get("status") == "success":
                        self.state = "verifying"
                        values = await self.bootstrap(client, result.get("bot_info") or {})
                        self.identity = await self.verify(values)
                        if not self.identity.get("ok"):
                            self.error = self.identity.get("code", "identity_failed")
                            self.state = "identity_failed"
                            return
                        self.save(values)
                        self.state = "connected"
                        self.svg = self.scode = ""
                        return
                    await asyncio.sleep(3)
                self.state = "expired"
        except asyncio.CancelledError:
            raise
        except Exception:
            self.state = "failed"
            self.error = self.error or "auth_network_or_protocol_error"
        finally:
            if self.state not in ("waiting_scan", "verifying"):
                self.svg = self.scode = ""

    def status(self) -> dict:
        return {
            "state": self.state,
            "error": self.error,
            "identity": self.identity,
            "credential_storage": "Windows user environment only",
        }


def create_auth_app(flow: AuthFlow | None = None):
    flow = flow or AuthFlow()

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(flow.run())
        try:
            yield
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def valid_host(request: Request) -> bool:
        return request.url.hostname in ("127.0.0.1", "localhost")

    async def home(request: Request):
        if not valid_host(request):
            return HTMLResponse("Forbidden", status_code=403)
        body = """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>Arena 企业微信接入</title><style>body{font:18px system-ui;background:#f5f5f4;color:#292524;max-width:620px;margin:48px auto;padding:24px}svg{width:300px;height:300px;background:white}section{background:white;padding:24px;border-radius:16px}h1{font-size:26px}</style>
<h1>Arena · 企业微信接入</h1><section><p>使用企业微信扫描二维码，并在手机端选择或创建本次比赛专用机器人。</p>
<p>凭据仅写入本机用户环境变量，不显示、不生成凭据文件。</p>"""
        body += flow.svg or "<p>二维码正在准备，或已完成／失效。</p>"
        body += "<p id='status'></p></section><script>async function tick(){let s=await(await fetch('/status')).json();document.getElementById('status').textContent='状态：'+s.state+(s.error?'；错误：'+s.error:'');if(s.state==='initializing')setTimeout(()=>location.reload(),1000)}setInterval(tick,1500);tick()</script></html>"
        return HTMLResponse(
            body,
            headers={
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "X-Frame-Options": "DENY",
            },
        )

    async def status(request: Request):
        return (
            JSONResponse(flow.status(), headers={"Cache-Control": "no-store"})
            if valid_host(request)
            else JSONResponse({}, status_code=403)
        )

    app = Starlette(routes=[Route("/", home), Route("/status", status)], lifespan=lifespan)
    app.state.auth_flow = flow
    return app

"""企业微信 SDK 接入候选。真实群收发尚待机器人创建后联调。"""

import asyncio
from collections import defaultdict

from aibot import WSClient, WSClientOptions, generate_req_id

from arena.config import Settings
from arena.harness import Harness
from arena.store import Store
from arena.wecom_auth import import_user_environment


class QuietLogger:
    """第三方 SDK 不输出原始帧、凭据或用户问题。"""

    def debug(self, *args):
        pass

    def info(self, *args):
        pass

    def warn(self, *args):
        pass

    def error(self, *args):
        pass


class WecomMessenger:
    def __init__(self, client: WSClient):
        self.client = client

    async def send(self, userid: str, text: str) -> bool:
        frame = await self.client.send_message(userid, {"msgtype": "markdown", "markdown": {"content": text}})
        # 必须收到明确成功回执；缺失 errcode 不当作投递成功。
        return frame.get("errcode") == 0


async def run_bot(
    settings: Settings, store: Store, status: dict | None = None, allow_offline: bool = False
) -> None:
    status = status if status is not None else {}
    status.update(state="starting", messages_received=0, messages_replied=0, error=None)
    if not settings.wecom_bot_id or not settings.wecom_bot_secret.get_secret_value():
        raise ValueError("请先在本机环境变量配置 WECOM_BOT_ID / WECOM_BOT_SECRET")
    if not settings.llm_api_key.get_secret_value() and not allow_offline:
        raise ValueError("请先配置 LLM_API_KEY，再启动 DeepSeek 机器人")
    client = WSClient(
        WSClientOptions(
            bot_id=settings.wecom_bot_id,
            secret=settings.wecom_bot_secret.get_secret_value(),
            max_reconnect_attempts=-1,
            heartbeat_interval=30000,
            logger=QuietLogger(),
        )
    )
    harness = Harness(settings, store, WecomMessenger(client))
    pending: dict[str, int] = defaultdict(int)
    seen: dict[str, float] = {}

    @client.on("authenticated")
    def on_authenticated():
        status.update(state="authenticated", error=None)

    @client.on("disconnected")
    def on_disconnected(reason):
        status.update(state="disconnected")

    @client.on("error")
    def on_error(error):
        status.update(error=type(error).__name__)

    @client.on("message.text")
    async def on_text(frame):
        body = frame.get("body", {})
        userid = body.get("from", {}).get("userid", "")
        content = body.get("text", {}).get("content", "")
        if not userid or not content:
            return
        # 平台对单聊/群 @ 消息触发回调；不可依赖回调正文保留 @ 字符。
        msgid = body.get("msgid", "")
        current = asyncio.get_running_loop().time()
        for old in [key for key, when in seen.items() if current - when > 600]:
            seen.pop(old, None)
        if msgid and msgid in seen:
            return
        if msgid:
            seen[msgid] = current
        status["messages_received"] += 1
        stream_id = generate_req_id("stream")
        if pending[userid] >= 3:
            await client.reply_stream(frame, stream_id, "请稍等，前面的消息还在处理中。", True)
            return
        pending[userid] += 1
        try:
            await client.reply_stream(frame, stream_id, "正在查…", False)
            import_user_environment(("DEEPSEEK_API_KEY", "LLM_API_KEY"))
            current_settings = Settings()
            harness.settings = current_settings
            use_llm = bool(current_settings.llm_api_key.get_secret_value())
            reply = await harness.ask(content, userid, use_llm=use_llm)
            answer = reply["answer"] if use_llm else "【离线演练，尚未连接 DeepSeek】\n" + reply["answer"]
            # SDK feedback 入参已核实，企业微信 feedback 事件解析尚未接入。
            result = await client.reply_stream(frame, stream_id, answer, True)
            if result.get("errcode") == 0:
                status["messages_replied"] += 1
            else:
                status["error"] = "reply_not_acknowledged"
            status["last_mode"] = reply["mode"]
        except Exception:
            await client.reply_stream(frame, stream_id, "处理失败，请联系主办方；本次未确认完成。", True)
        finally:
            pending[userid] -= 1

    @client.on("event.enter_chat")
    async def on_enter(frame):
        await client.reply_welcome(
            frame,
            {
                "msgtype": "text",
                "text": {"content": "可询问作品编号、提交规范或岗位问题。当前为测试机器人。"},
            },
        )

    try:
        await client.connect()
        await asyncio.Event().wait()
    finally:
        client.disconnect()

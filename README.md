# Arena · ANC 比赛运行层 demo

这份 demo 将 Notion 方案中的提交、查询、知识答疑、值班和反馈流程变成可运行代码。
当前已完成**本地业务闭环、ABF 企业微信身份绑定、四张真实测试子表、机器人单聊收发及反馈回写**。
DeepSeek 尚待密钥验证，GitHub App 写入器和公网 MCP 尚未接通。

## ABF 真实联调入口

- 比赛登记表：ABF · Arena 比赛运行层 Demo，真实链接仅保存在本机 `SMARTSHEET_URL` 环境变量。
- 本机服务：`http://127.0.0.1:8765/mcp`，健康状态：`http://127.0.0.1:8765/healthz`。
- 企微机器人：`test机器人`。真实发送“山海队的作品ID”已收到正确回复，并在企微「反馈」表读回对应记录。
- 本机 DeepSeek 密钥接入页：`http://127.0.0.1:18767`，由用户输入密码框；验证一次真实工具调用后才写本机用户环境变量，不经过聊天。
- 机器人未配置模型时明确回复“离线演练，尚未连接 DeepSeek”。这是显式允许的演练模式。

重新启动真实企微 demo：

```powershell
.\Run-Demo.ps1 -Mode live
```

仅运行一个实例；已运行时不要重复启动，以免同一机器人长连接相互挤占。
「作品、版本、反馈」由本地业务状态同步到企微，工作人员补充的作品别名每约 60 秒回流。
本阶段是**云端登记镜像**，SQLite/Git 仍维护提交事务。密钥及密钥哈希不上传；表中密钥哈希字段预留为空。值班表结构已创建与写入，动态值班回流仍待完整接入。

身份映射也需区分：CLI 授权用户与机器人消息回调的标识可能不同；目前真实单聊按 participant 权限通过，工作人员和管理员消息身份仍待核对，不能以 CLI 登录代替 staff 角色验收。

## 直接运行（Windows PowerShell）

在本目录执行：

```powershell
.\Run-Demo.ps1
```

会自动用 `uv` 安装锁定依赖并执行：三队报名 → 两版提交 → 拒收缺 README → 查询固定编号 → 规则答疑 → 转人工待办 → 点踩报告。
在本次 Codex 工作目录中，虚拟环境和运行数据保存在 `work/`，源代码放在 `outputs/arena/`。
重复执行会保留历史并新增版本；只重置演练队伍密钥。示例数据均为虚构。

验证真实 MCP 协议：

```powershell
.\Run-Demo.ps1 -Mode mcp-walkthrough
```

该命令启动临时 localhost TCP 服务，用**官方 MCP 客户端**完成 initialize、tools/list、tools/call，检查无效密钥 401、缺 README 拒收、提交与版本读取、两队隔离，然后自动关闭临时服务。
队伍密钥在当前进程环境中生成与使用，不输出、不写入明文文件。

检查外部工具（只读，不发消息、不写表格、不写 GitHub、不调用模型）：

```powershell
.\Run-Demo.ps1 -Mode selftest
```

启动长期运行的本机 MCP 服务：

```powershell
.\Run-Demo.ps1 -Mode serve
# GET http://127.0.0.1:8765/healthz
# MCP http://127.0.0.1:8765/mcp
```

此服务使用 SQLite 中已有队伍密钥哈希验证调用方。对外部 MCP 客户端接入，先用本机环境变量配置一枚队伍密钥，再执行 `uv run arena bind-key H-001 --env-name ARENA_TEAM_KEY`。客户端需要从它自己的本机环境读取相同密钥。
`serve-demo` 的随机密钥仅在服务进程内，主要用于开发；完整自动演练请用 `mcp-walkthrough`。

## 已实现的行为

- **登记与身份**：SQLite 中的作品、版本、值班、反馈四张表；三位补零编号；按队名幂等导入；仅保存队伍密钥的 SHA-256。机器人身份通过工作人员与管理员白名单判断。
- **提交**：MCP 三个工具 `submit_work`、`get_my_work`、`list_my_versions`；作品身份取自 HTTP Bearer 密钥，工具参数没有 `work_id`；工具执行时再次验证密钥。
- **检查**：README、截止时间、路径穿越、Windows 特殊文件名、大小、重复内容、base64、路径冲突；README 太短给出提示。为符合本次“凭据不得上传”要求，疑似 `.env`、API Key 或私钥**阻断**，比原规格的警告更严格。
- **版本**：真实本地 Git commit 与 `H-xxx/vN` tag，整体替换本作品目录，保留其他作品。单服务的异步锁串行处理提交，验证过 20 并发版本分配。
- **答疑与权限**：模糊匹配、中文 BM25、按角色隔离 SOP 和作品详情；Skills YAML 启动校验；基于工具原始结果生成有来源的回复；模型不可自由编造作品 ID。
- **反馈**：按当前时段找负责人；离线模式只记录待转人工，不声称投递成功；反馈记录和 CLI 点赞点踩。
- **DeepSeek 接口**：实现 tool calling 循环、按角色提供工具、每工具内部再验权、4 轮上限、30 秒请求与 60 秒整体超时。接口已用假响应验证，未使用真实 API Key 调用。
- **企业微信 SDK 接口**：长连接、流式回复、进入会话欢迎语、限并发、重连和主动通知适配器；单聊真实收发通过，群 @、原生点赞事件和真实转人工投递仍待分别验收。
- **企微云端桥接**：四表创建和字段读回、真实记录写入回读、演练业务状态镜像、对话反馈回写、别名回流；同步失败保留本地状态并在健康接口报告失败。

## 两种答疑模式

```powershell
uv run arena ask '山海队的作品ID'
uv run arena ask '怎么提交'
uv run arena ask '签到怎么处理' --userid demo-staff
```

默认为 `offline-scripted`：本地确定性路由，**没有调用大模型**。需要演练工作人员身份时，先把 `demo-staff` 加入本机 `STAFF_USERIDS` 环境变量。

真实 DeepSeek 模式要求在本机环境配置 `LLM_API_KEY`（或 `DEEPSEEK_API_KEY`）、`LLM_BASE_URL`、`LLM_MODEL`，再执行：

```powershell
uv run arena ask '山海队的作品编号是多少' --llm
```

默认地址 `https://api.deepseek.com`，模型名 `deepseek-flash`，依据 2026-10-28 官方文档；可通过环境变量覆盖。调用会发送问题、可用工具和检索结果到所配置模型地址。
没有密钥时显式报错；不会默默把离线路由伪装成模型结果。代码不自动读取 `.env` 文件。

## 外部系统接入状态

| 项目 | 本次实际状态 | 后续事项 |
| --- | --- | --- |
| Python / uv / Git | Python 3.12.14、uv 0.12.18、Git 可运行 | 使用锁定环境 |
| 企业微信 CLI | 1.3.4；扫码绑定后真实身份查询通过，40125 已排除 | token 通过用户环境变量提供 |
| 企业微信机器人 | test机器人长连接已认证；真实单聊收到并回复 1 条 | 继续验收群 @、工作人员角色和转人工 |
| 企业微信智能表格 | 四表已创建，字段、记录写入与回读通过；用户真实消息反馈已回写 | 继续完善完整 Registry 与值班回流 |
| GitHub | `gh` 已登录，能够读取账户信息 | 专用作品仓库与 GitHub App 未配置；本 demo 不向公网提交作品 |
| DeepSeek | 接口代码与假响应测试完成；未检测到 API Key | 本机环境配置后真实请求验收 |
| Docker | 已启动 Docker Desktop，引擎 29.8.2 可响应；容器验收见 CHECKS.md | 使用本地容器演练 |
| 公网 MCP / HTTPS | 本机 HTTP 协议已验证，尚无公网地址 | 确认服务器与 HTTPS 域名，再做远程客户端验收 |

**CLI 与自建应用是不同凭据体系。** 官方 CLI 支持智能表格管理，不代表常驻服务已经拥有自建应用 `access_token`、可信 IP 或真实数据读写权限。
本 demo 不复制或解密 CLI 既有凭据，也未执行会新增凭据文件的 `auth init`。
`arena connect-wecom` 按官方开源扫码和签名协议完成绑定，将机器人凭据与 `WECOM_CLI_ACCESS_TOKEN` 直接写入 Windows 用户环境变量。CLI 子进程从该环境取 token；原有凭据文件保持不动。环境 token 的自动续期仍需后续接入。

## 当前与完整规格的差距

这不是 M1–M8 全部完成的交付。以下内容尚未实现或验收：

- 以智能表格为主存储的完整 Registry。当前已实现约 60 秒登记镜像和作品别名回流；完整值班和其他人工编辑字段回流未实现。
- GitHub App 写入器、分支冲突重试、自动 pending-sync 恢复。当前登记失败会保留 `pending_sync.jsonl`，由人工核对；已有 tag 冲突会停下，不覆盖。
- `repo_url` 大作品拉取、公开仓库大小限制与指定 ref 提交。
- 企业微信群 @ 真实验收、原生反馈事件解析、投递权限、断线后的端到端恢复。
- 完整报名发密钥与密钥分发流程。CLI 不打印明文，也不生成 `credentials.csv`；导入时生成的临时密钥随进程结束不可恢复，可通过 `bind-key` 重新绑定本机环境变量中的密钥。
- 公网 HTTPS、Claude Code / Cursor 真实远程接入、企微端到端重连与长期运行验收。

ABF 测试表目前将状态、事项类别、来源和评价作为文本字段以便演练；生产 schema 的单选约束尚未落实。
Windows Python 3.12 的 WMI 系统查询在本机实测挂起，项目启动时禁用可选 `_wmi` 导入，使用 stdlib 原有 Win32 回退；未修改系统 WMI 服务或 Python 安装目录。

## 测试

```powershell
uv run pytest -q
uv run ruff check .
uv run mypy src
```

默认测试通过 socket 限制阻止外网连接，仅 localhost MCP 协议测试使用真实 TCP。DeepSeek 用 `respx` 假响应；所有演练均不发送真实企业微信消息。

Docker 本机启动：

```powershell
docker compose up --build -d
# 查看本机健康接口：http://127.0.0.1:8765/healthz
docker compose down
```

Compose 只启动本地模式 MCP，不注入企业微信、GitHub 或模型凭据。真实云端系统另行联调。

## 来源

- [Notion 总方案](https://app.notion.com/p/406a4d98cffb80aca765c48f98108870)
- [详细搭建规格](https://app.notion.com/p/3945e01d2d8349609df852f82d43d4ef)
- [企业微信官方 CLI](https://github.com/WecomTeam/wecom-cli)
- [CLI 参数与环境变量](https://github.com/WecomTeam/wecom-cli/blob/main/docs/cli-reference.md)
- [企业微信机器人 Python SDK](https://github.com/WecomTeam/wecom-aibot-python-sdk)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [DeepSeek Tool Calls](https://api-docs.deepseek.com/guides/tool_calls/)
- [DeepSeek 模型列表](https://api-docs.deepseek.com/quick_start/pricing/)

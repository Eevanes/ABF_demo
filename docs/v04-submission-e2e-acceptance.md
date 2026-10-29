# v0.4 真实选手提交验收

状态：真实 GitHub／智能表格全链路尚未执行。缺少 GitHub App 四项环境配置；当前本地验证仅证明验收驱动及既有业务逻辑可运行。

## 运行入口

```powershell
# 配置检查，不联网、不写入
.\Run-Demo.ps1 -Mode doctor-v04
.\Run-Demo.ps1 -Mode v04-submission-check

# 只有显式执行才会产生真实测试作品与沙盒记录
uv run --frozen python scripts/v04_submission_acceptance.py --execute

# 只读独立 v0.4 五表沙盒，不回退读取运营表
uv run --frozen arena doctor-v04 --live-read
```

真实执行所需：`GITHUB_APP_ID`、`GITHUB_INSTALLATION_ID`、`GITHUB_APP_PRIVATE_KEY`、`GITHUB_REPO`，可选 `GITHUB_BRANCH`。均通过本机环境传入。App 安装在专用作品测试仓库，只授予实际需要的 Contents 写权限；分支须已初始化。脚本拒绝使用 `Eevanes/ABF_demo` 作为作品目标。

企业微信 CLI 需能访问智能表格。首次执行在 App 分支读取通过后创建独立的 v0.4 五表沙盒，将新 ID 保存至 `ARENA_V04_SMARTSHEET_DOCID` 用户环境变量；绝不覆盖 `SMARTSHEET_DOCID`。已有 v0.4 沙盒时先检查五表 schema，不自动修改现有字段或记录。每次生成两支新虚构队伍，避免覆盖上次演练作品。测试队伍凭据只在进程内生成，不进入表格或证据文件。

## 驱动实际验证的内容

1. 使用官方 MCP 客户端，经真实 localhost TCP 分别认证两个队伍；工具参数没有任意作品 ID。
2. 两队各提交 v1/v2，复用同 `submission_id` 重试并核对原结果。
3. 读 GitHub tag、SHA、SUBMISSION 元数据和文件正文，核对表格版本行、最新指针及 MCP 历史。确认 v2 删除了旧脚本。
4. 第二队 v1 在真实 GitHub 写入后，本地故意阻断登记；验证持久化待恢复操作，再调用与 `arena reconcile` 相同的业务方法补登记，SHA 不变且不重复上传。
5. 验证错误凭据、同编号改内容、恶意路径和过期新请求被拒绝，不新增版本。

脚本不测试真实公网断网、远程 HTTPS、真人企微身份、消息投递或工单接单。离线测试使用本地 Git 和明确的测试双替身验证驱动流程，不是 GitHub 实写。

## 证据与中断恢复

成功报告写在 `.arena/v04-acceptance/<run-id>/report.json`，包含真实作品链接、tag、SHA、请求编号和检查结果。此目录受 Git 忽略；去敏审查后再将结果摘要加入本文件，禁止直接提交整个运行目录。

失败时控制台只输出安全的错误类别／代码，不输出 API 响应或凭据。已经形成的 journal 与 GitHub／表格证据保留，不能当作临时文件删除。不要对同一 run-id 重新生成队伍凭据。对已进入提交阶段的中断，在确认同一专用目标后，设置：

```powershell
$env:ARENA_REGISTRY = 'smartsheet'
$env:ARENA_WRITER = 'github'
$env:SMARTSHEET_DOCID = $env:ARENA_V04_SMARTSHEET_DOCID
$env:ARENA_SMARTSHEET_WRITES_ENABLED = 'true'
# ARENA_DATA_DIR 指向此次 .arena/v04-acceptance/<run-id> 的绝对路径
uv run --frozen arena reconcile
```

这些仅对当前进程设置，使用独立终端并在结束后恢复；不写入用户环境中的运营表设置。`planned` 阶段若 Git 没有证据，需原请求原文件重试，不能凭空补造作品。若首次建表中途失败，保留新表 ID，核对缺失子表后再处理，不使用运营表代替沙盒。

## 当前结果

| 层次 | 结果 |
| --- | --- |
| v0.3 基线 | 本轮重跑 76 项测试、Ruff、mypy 和 25/25 服务 Evals 通过 |
| v0.4 验收驱动 | 本地 Git＋官方 MCP 协议、两队两版及登记故障补偿已通过自动测试 |
| GitHub App 实写 | 未执行；四项 App 环境配置缺失 |
| v0.4 智能表格 | 未创建；等待 App 接入后执行，避免留下无作品证据的假版本 |
| 远程 HTTPS | 未配置，TLS、远程客户端和限流边界待验收 |

完成真实执行后，登记日期、代码 SHA、真实报告摘要、两队版本链接和异常补偿证据。仅配置齐全或本地演练成功不能将本表改为“全链路通过”。

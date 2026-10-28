# v0.3 运行与现场恢复

## 本地检查

在仓库根目录执行 `./Run-Demo.ps1 -Mode verify`，包含 pytest、ruff、mypy。
启动器仅对其子进程启用 CPython 3.12 的 WMI 回退，结束后恢复原 PYTHONPATH；不修改系统 WMI 设置。
选手协议演练使用 `./Run-Demo.ps1 -Mode mcp-walkthrough`。

## WorkBuddy 只读 PoC

1. 使用独立的 WorkBuddy-Arena 测试机器人；保留现有 test机器人及其服务。
2. 本地设置 ARENA_REGISTRY=smartsheet，保持所有写开关关闭。
3. `./Run-Demo.ps1 -Mode serve-staff -Port 8766`；WorkBuddy 使用 HTTP MCP `http://127.0.0.1:8766/mcp`。
4. 不设置 staff Bearer，调用 search_works 查询山海队，核对真实表中的 H-001。
5. 分别验证单聊、群 @、会话隔离和 sender 身份；云端 WorkBuddy 需独立公网 HTTPS 地址，不能访问本机 localhost。

首批五项 Skills 与系统提示在 workbuddy/。规则目录的既有内容是示例，没有发布审批元数据时不会作为正式规则返回。
由赛事规则 Owner 审核规则 Markdown，填写 policy_id/version/effective_at/approved_by/source_url/content_hash/allowed_roles。
规则加载成固定快照，改版后重启并做同一组评估；ARENA_POLICY_RELEASE 记录提交采用的发布包版本，默认 demo-unpublished。

## 存储切换

配置项只放本地进程/用户环境，文档和配置模板不填真实值：

| 配置 | 用途 |
| --- | --- |
| ARENA_REGISTRY=local 或 smartsheet | 业务台账适配器 |
| SMARTSHEET_DOCID | 目标赛事表；切换前先核对专属目标和五表 schema |
| ARENA_SMARTSHEET_WRITES_ENABLED=true | 目标 schema 验证通过后允许表写 |
| ARENA_TEAM_CREDENTIALS | 队伍凭据摘要映射，只存本机环境 |
| ARENA_WRITER=local 或 github | 文件写入适配器 |
| GITHUB_APP_ID / GITHUB_INSTALLATION_ID / GITHUB_APP_PRIVATE_KEY / GITHUB_REPO | GitHub App；安装到专用作品仓库，只需 Contents 写权限 |
| GITHUB_BRANCH | 已初始化的分支，默认 main |
| ARENA_STAFF_CREDENTIALS | 独立工作人员凭据摘要及可信身份映射 |
| ARENA_STAFF_WRITES_ENABLED | 工作人员写操作开关；身份验收前关闭 |

GitHub 私钥只从环境读取；安装 Token 仅在服务内存短期持有，不写磁盘。
启用云 Registry 前执行 `SmartSheetRegistry.verify_schema()`；不会自动修改已有表或覆盖人工记录。
`arena doctor-v03 --live-read` 只读真实作品数和脱敏状态，不发消息、不创建 Token、不写表。
正式写入演练需要已配置 GitHub App、独立作品仓库和明确赛事表；本次缺失配置见状态报告。

## 提交故障

客户端每次新的提交生成一个 submission_id，并在重试中保持它及文件/标题/说明不变。
响应失败后先查询版本；Git 已保存而表登记失败时执行 `arena reconcile`。
命令输出 reconciled/pending；有 pending 时退出码 1，保持证据并查明冲突。
服务启动后及每60秒也检查待恢复操作。v0.2旧 pending_sync.jsonl 保留人工核对，未解决时健康接口仍为503。
未写入 Git 的 planned 操作需要原文件重试，自动对账不会凭空重建文件。
健康接口遇到未解决操作返回 503；HTTP 200 只证明当前 Arena 业务状态，不证明 WorkBuddy/企微全链路正常。

## 切回旧入口

停止新服务，撤销其工作人员写开关，恢复 ARENA_REGISTRY=local / ARENA_WRITER=local。
只有在确认旧 Store 仍对应正确测试数据时启动旧 `live`；云端已产生正式新版本时先对账迁回，不能直接切到过期 SQLite。
同一 Bot ID 只保留一个长连接；迁移前后各保存读回证据。

## 人工接管

通知失败保留工单与 outbox 待处理，不回复“已通知”。工单负责人按状态机接单并附依据结案。
无当班负责人交固定 Owner；换班保留未关闭工单的原 DRI，明确交接后才重新分配。
赛前由主办方填写赛事 Owner、技术 Owner、值班备份和紧急联系方式，真实身份不填进开源模板。

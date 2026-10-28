# v0.3 交付与验收状态

日期：2026-10-28。代码基线：main `703c048`。迭代分支：`feat/arena-v03-workbuddy-anc`。
本次交付为 `0.3.0.dev1`，正式赛事运行尚未切换。

| 阶段 | 已完成及证据 | 尚未验收 |
| --- | --- | --- |
| 0 基线与接入 | 原仓库已固定 SHA；真实四表只读与官方 MCP 客户端验证通过；WorkBuddy主界面、用户首次信任、本机MCP连接及真实模型查询均通过；用户授权沿用原test机器人，企微私聊只读闭环通过 | 账号/Enterprise资格、群@、企微多用户会话隔离及sender透传未验证 |
| 1 工作人员层 | 独立工作人员 MCP、可信身份映射、作品范围隔离、共享 QueryService、规则发布快照、五项 Skill 草案；WorkBuddy真实调用search_works返回H-001，get_work被匿名权限拒绝 | 五项Skill触发全面评估、企微问答正确率、旧新入口双轨比较 |
| 2 存储与恢复 | Registry/GitHub App Writer、幂等提交、持久化操作日志、启动及每60秒对账、故障重试；独立五表沙盒真实补登记/排班读回通过 | GitHub App安装与专用作品仓库未配置，GitHub实写及正式台账迁移未执行 |
| 3 工单与DRI | 状态机、唯一负责人、接单/改派/证据结案、超时升级、审计/outbox；真实沙盒经MCP创建→接单→处理→解决→结案读回通过 | 默认无真实通知Provider，通知保持queued；真实投递及接收人回执、换班真人演练待完成 |
| 4 反馈与评估 | 反馈审查、改进草案、25题固定确定性服务评估、运行/回退手册、CI | 真实Agent评估、Owner/Reviewer审批发布、至少一次反馈改进发布回归、5–10人赛前演练和长期稳定性 |

## 验证证据

- `Run-Demo.ps1 -Mode verify`：pytest、ruff、mypy；数量与范围见 [验证记录](v03-verification.json)。
- `evals/run.py`：25/25确定性服务评估，不调用模型，不代表WorkBuddy回复验收。
- `scripts/v03_readonly_probe.py`：旧测试表→真实localhost MCP，公开查询准确且匿名内部查询被拒绝。
- [五表适配器真实沙盒报告](v03-cloud-acceptance.json)：登记故障补写、去重、排班直接修改读回、工单持久化。
- [真实沙盒MCP工单报告](v03-cloud-mcp-acceptance.json)：独立临时测试身份完整状态流；无真实消息发送。
- [WorkBuddy桌面本机联调报告](v03-workbuddy-local-acceptance.json)：Hy3真实模型通过arena-local查询山海队，返回H-001/RAG知识助手，内部详情被服务端权限拒绝。
- [企微私聊真实联调报告](v03-wecom-acceptance.json)：原test机器人经用户授权由WorkBuddy接管；用户发送只读查询并收到H-001/RAG知识助手及内部详情拒绝回复，后台同期两次MCP调用。未向原ABF群发送测试消息。
- GitHub Writer 的 App Token、分支冲突、tag故障恢复仅通过Mock HTTP测试；没有把模拟SHA当作正式作品证据。

首次基线30项测试出现过一次jieba加载MemoryError；后续隔离回归通过。启动器增加本进程WMI回退，未改系统设置。
新建了一份独立的v0.3五表验收沙盒，只有虚构数据；原SMARTSHEET_DOCID及四表未迁移。后续用户明确授权WorkBuddy接管原test机器人，私聊只读查询仍使用原测试表；旧8765服务不可达，未执行停止旧进程操作。
专用沙盒ID只保存在本机用户环境 `ARENA_V03_SMARTSHEET_DOCID`，验收报告不包含可用凭据或真实人员标识。

## 下一步实际接入条件

1. WorkBuddy桌面及原test机器人私聊只读MCP联调已通过；下一步验证群@、多用户会话隔离和可信sender身份，并明确正式运行采用桌面还是Enterprise。
2. GitHub实写需配置 GitHub App ID、Installation ID、Private Key及专用作品仓库；云端模式另需可达的 MCP HTTPS 地址。本轮本机原生渠道已用localhost跑通，无需公网MCP。
3. 明确唯一赛事 Owner/Reviewer、通知Provider和回执语义，审批正式规则及Skill包。

这些条件补齐前继续使用公共只读接入和隔离沙盒，不开放共享机器人管理员权限。
完整运行与恢复步骤见 [运行手册](v03-runbook.md)。

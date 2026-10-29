# v0.4 接入、演练与切换

当前交付范围：代码与联调准备。企业版未开通、App 尚未创建、正式测试资料和双人演练条件未齐，真实验收继续标记待进行。阶段状态见 [v04-status.md](v04-status.md)。

## 现在可运行

```powershell
.\Run-Demo.ps1 -Mode verify
uv run --frozen python evals/run.py
.\Run-Demo.ps1 -Mode doctor-v04
.\Run-Demo.ps1 -Mode v04-submission-check
```

前两项是本地测试与确定性服务 Evals；后两项是无写入的配置检查。`doctor-v04 --live-read` 仅访问独立 v0.4 沙盒，不以运营表兜底。`https_url_syntax_valid` 只检查地址形式，TLS、DNS、真实远程 Agent 和服务稳定性须另测。

## GitHub App 接入准备

在 GitHub 为专用作品测试仓库建立 App 安装，使用 Contents 写权限及必要的 Metadata 读权限，初始化测试分支。App 尚未创建前无需打开表格写开关。

运行环境需要 `GITHUB_APP_ID`、`GITHUB_INSTALLATION_ID`、`GITHUB_APP_PRIVATE_KEY`、`GITHUB_REPO` 和可选 `GITHUB_BRANCH`。实际值通过本机环境变量注入，私钥不放项目文件、资料库、表格、配置下载包或聊天；示例文件只有变量名。现有 App Writer 会按配置的单个仓库申请安装 Token。

配置完成后执行 [真实提交演练](v04-submission-e2e-acceptance.md)。默认 dry-run；`--execute` 才创建独立五表沙盒和真实测试作品。失败保留 journal 和云端证据；重试前使用原提交编号并核对，不清空版本台账。

## WorkBuddy 原生包接入准备

开通相应企业版并确认测试机器人可使用原生资料与表格能力后，先恢复原测试范围的授权。Owner 确认四类测试文档及版本、角色、来源；只使用虚构运营数据做演练。

候选文件位于 `workbuddy/native/`，当前正式依赖仍为 `workbuddy/skills/` 兼容包。候选包中的 [能力绑定表](../workbuddy/native/CAPABILITIES.md) 是发布记录，不是可直接导入的 WorkBuddy API 配置；实际工具名须从该环境的执行记录核验并填入。

按 [26 项真实题集](../evals/workbuddy_cases.md) 逐题记录结果。先做知识和普通查表，再做双人隔离、内部资料权限与错误分支。用户确认“产品支持”不能代替该环境的真实结果；桌面成功也不能代替企微成功。

上述能力通过后，再由 Owner/Reviewer 审核、装载原生提示与五项 Skills；同名旧 Skills 从运行配置移除，兼容代码仍保留回退。逐项证明原生覆盖后再缩减重复知识和普通查表工具。当前不停止 8766，也不启动旧 Bot 长连接。

## DRI、通知和反馈

工单继续使用已有独立工作人员认证和受控状态机。本人接单、管理员改派与结案不能通过直接编辑表格系统字段实现。未验证可信 sender 的共享机器人保持公共只读；独立协议演练身份不等于企微本人身份。

通知 Provider 当前未装配，outbox 状态保持 queued，不宣称已通知。接入 Provider 时须验证平台真实回执、失败重试及接收人；只返回 `errcode=0` 而无平台回执的接口不满足当前 Notifier 契约。平台接受与本人接单分别留证。三次异常演练各记录 ticket_id、DRI、状态、投递结果、处理证据与结案。

反馈改进使用 F01/F02：匿名反馈 → 问题分类 → 草案 → Owner/Reviewer 审核 → 测试 → Git 发布版本 → 同一问题在原企微渠道回归。候选 Skill 包本身不算已完成这条真实闭环。

## 远程试用与回退

其他电脑接入前部署具有持久化操作日志的单实例 Arena，配置 HTTPS、队伍认证和网络访问范围，再验证 TLS、限流、健康检查及断连恢复。当前 Dockerfile 没有完成云端企微 CLI 授权装配；保持本地模式，不能因镜像存在而宣布云端已部署。

3–5 位同事各自登录演练：从哪里提问、从哪里提交、在哪里看版本、异常找谁。当前没有试用和长时间稳定性证据。

回退时恢复兼容提示和 Skills、关闭工作人员写开关；保留当前操作日志并先对账。GitHub 或表格已产生新版本时，不用旧 SQLite 覆盖云端。完整历史回退边界见 [v0.3 运行手册](v03-runbook.md)。

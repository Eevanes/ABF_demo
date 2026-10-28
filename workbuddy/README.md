# WorkBuddy 接入包

本包为 v0.3 草稿，五项 Skill 已按实际 Arena 工具契约编写；Owner/Reviewer 仍需由赛事方指定并审批发布。仓库旧知识属于示例，默认不会作为已发布规则返回。

先运行 `arena serve-staff`（默认本机8766端口，请以 `--help` 为准）。在 WorkBuddy 自定义 MCP 中填写该运行环境能够访问的 `/mcp` 地址。桌面本机可用 localhost；云端须经实际验证的 HTTPS 地址。

公共只读连接不带凭据，只可查询公开字段。独立认证连接的 Authorization 从 WorkBuddy 凭据/环境读取，服务端 `ARENA_STAFF_CREDENTIALS` 保持token摘要→可信userid/role/works范围的映射。企微原生sender尚未透传验证时，不能把共享机器人静态token当成每个员工身份，写工具保持禁用。

挂载工单 backend 且 `ARENA_STAFF_WRITES_ENABLED=true` 后才提供受控工单写入；正式接入前验证会话隔离与真实身份。`list_feedback`/`list_tickets`/`propose_change`仅Admin可用，改进建议不等于发布。

按以下顺序真机验收：专用测试Bot → 单聊及群@ → 只读MCP真实查表 → sender与会话隔离 → 独立身份受控操作 → 通知平台回执 → 重启恢复。沿用现有Bot只会导致长连接竞争，测试应使用专用机器人。

`python evals/run.py` 的结果是确定性服务评估，未调用WorkBuddy或真实模型。Skill实际触发、回复引用与角色隔离仍需用同一cases进行真实Agent复测。Skill发布需记录版本、Git commit、审批人、发布时间和回滚点。

运行时配置只通过本机环境变量提供；此目录没有真实token或完整连接凭据。正式台账在智能表格，OperationJournal仅保存操作审计、通知意图和改进草稿；SQLite工单backend仅供离线演练。

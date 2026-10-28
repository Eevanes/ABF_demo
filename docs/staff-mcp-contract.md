# 工作人员 MCP v0.3 契约

传输：Streamable HTTP，默认 `http://127.0.0.1:8766/mcp`；选手接口为另一个服务与权限域。
身份来自服务端独立 Bearer 摘要映射，所有工具重新验证身份，不接受调用方传 userid 或 role。

| 工具 | 主要输入 | 返回/约束 |
| --- | --- | --- |
| search_works | query | candidates、requires_confirmation；公共角色只检索公开字段，多候选不猜 |
| get_work / list_all_versions | work_id | 内部作品/版本证据；需 staff/admin 且在 work_ids 授权范围 |
| search_public_policy | query | 已审批生效 sources 及 snapshot_at；空结果即无已发布依据 |
| search_internal_sop | query | 内部已发布来源；要求 staff/admin |
| get_on_duty | category | 当前值班或 null；不得编造当班人 |
| create_ticket | request_id、summary、category、work_id、evidence_urls | 唯一 ticket_id、DRI、状态及通知状态；同请求异内容拒绝 |
| get_my_tickets / list_tickets / get_ticket | ticket_id（单条） | 当前身份发起/负责或 admin 授权工单 |
| acknowledge_ticket / start_ticket | ticket_id | 仅当前 DRI 或管理员按状态机更新 |
| resolve_ticket | ticket_id、resolution、evidence_urls | 必须附处理说明和 HTTPS 证据 |
| close_ticket | ticket_id | 请求人或管理员确认结案 |
| assign_ticket | ticket_id、assignee_userid、reason | 仅管理员改派；操作者不可伪造 |
| list_feedback | 无 | 仅管理员审查现有待审反馈 |
| propose_change | feedback_id、summary、issue_url（可选） | 针对真实反馈记录 proposed 草案，不发布规则、不自动创建远端 Issue |

任何写操作还要求服务端明确启用 ARENA_STAFF_WRITES_ENABLED。表格写入另受 ARENA_SMARTSHEET_WRITES_ENABLED 控制。
权限错误与业务校验错误通过 MCP tool result 的 isError 返回；无效 Bearer 在 HTTP 层返回 401，请求过大返回 413。
选手 submit_work 新增可选 submission_id：新提交用新 ID，重试沿用；同队同 ID 异内容拒绝，已成功的重试返回原版本。

通知 queued 表示等待投递；sent 仅表示配置的通知适配器返回了平台回执；acknowledged 是接收人确认。
当前默认没有真实通知适配器，不会把 queued 写成“已通知”。Provider 的幂等保障须在接入时单独验收。

草案、示例规则及未经审批 Skill 不能冒充正式赛事政策。发布需 Owner/Reviewer 审核、固定评估通过和版本回滚点。

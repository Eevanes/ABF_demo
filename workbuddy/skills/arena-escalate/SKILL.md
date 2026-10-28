---
name: arena-escalate
description: 查询无依据、提交记录异常或人工争议需要生成并追踪工单时使用。
owner: 赛事运营Owner（待指定）
reviewer: 独立Reviewer（待指定）
version: 0.3.0
status: draft
allowed_roles:
- staff
- admin
tools:
- create_ticket
- get_ticket
- acknowledge_ticket
- start_ticket
- resolve_ticket
- close_ticket
- assign_ticket
inputs: request_id, summary, category, work_id?, evidence_urls?
output_schema: ticket_id, assigned_userid, status, notify_status, notify_receipt
sources:
- Arena MCP tool results
- Git-managed approved policy release
escalation: 人工Owner；投递未确认则明确待处理
failure_modes: identity_unverified / writes_disabled / delivery_failed / no_owner
eval_cases:
- ticket-cross-role
- ticket-duplicate
- ticket-receipt-required
- ticket-escalate
- ticket-resolve-evidence
---

1. 仅在服务端显式启用写工具且身份/会话验证通过后执行；否则报告需独立认证。
2. create_ticket 使用稳定请求幂等键；保留 ticket_id、assigned_userid、status 和 notify_status。
3. 只有 notify_status=sent/acknowledged 且有 notify_receipt 时说明平台已接收通知；接单确认是单独动作。
4. 负责人接单、开始处理，解决时提供说明及HTTPS证据；请求人或管理员确认结案。
5. 管理员改派须原因；处罚和规则裁决提交人工审核。

---
name: arena-volunteer-sop
description: 志愿者询问签到、值班岗位、交接班和内部操作流程时使用。
owner: 赛事运营Owner（待指定）
reviewer: 独立Reviewer（待指定）
version: 0.3.0
status: draft
allowed_roles:
- staff
- admin
tools:
- search_internal_sop
- get_on_duty
inputs: 'question: string, category: string'
output_schema: sop, policy_version, source_url, duty
sources:
- Arena MCP tool results
- Git-managed approved policy release
escalation: 人工Owner；投递未确认则明确待处理
failure_modes: forbidden / no_duty / missing_sop
eval_cases:
- policy-internal-forbidden
- duty-empty
---

1. 确认工具提供的独立工作人员身份；普通聊天自报职位不构成认证。
2. 分别查询已发布内部 SOP 和当前值班负责人。
3. 缺班次则说明暂无当班记录，建议固定Owner处理；回复附规则版本和岗位来源。

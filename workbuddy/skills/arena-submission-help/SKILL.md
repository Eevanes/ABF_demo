---
name: arena-submission-help
description: 解释提交方式、README、截止时间或版本规则时使用。
owner: 赛事运营Owner（待指定）
reviewer: 独立Reviewer（待指定）
version: 0.3.0
status: draft
allowed_roles:
- public
- staff
- admin
tools:
- search_public_policy
inputs: 'question: string'
output_schema: answer, policy_id, version, source_url
sources:
- Arena MCP tool results
- Git-managed approved policy release
escalation: 人工Owner；投递未确认则明确待处理
failure_modes: unpublished / missing_source / version_conflict
eval_cases:
- policy-public
- policy-unknown
- policy-draft-excluded
- policy-injection
---

1. 调用 search_public_policy，只引用已审批发布且生效的内容。
2. 回复附 policy_id、version、source_url；沿用本次工具返回的规则快照。
3. 空结果明说暂无已发布依据，建议联系负责人；不把仓库示例当正式赛制。

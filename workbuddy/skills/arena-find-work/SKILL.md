---
name: arena-find-work
description: 按队名、作品名或别名定位作品，或查询作品版本时使用。
owner: 赛事运营Owner（待指定）
reviewer: 独立Reviewer（待指定）
version: 0.3.0
status: draft
allowed_roles:
- public
- staff
- admin
tools:
- search_works
- get_work
- list_all_versions
inputs: 'query: string'
output_schema: work_id, team, title, evidence
sources:
- Arena MCP tool results
- Git-managed approved policy release
escalation: 人工Owner；投递未确认则明确待处理
failure_modes: no_match / ambiguous / forbidden
eval_cases:
- query-team
- query-ambiguous
- query-public-detail-forbidden
---

1. 调用 search_works，公开查询使用公开身份。
2. 结果为空则明说未找到；多个候选列出编号与队名，等待用户确认。
3. 查询详情或版本前，使用独立认证的工作人员身份并限定作品范围。

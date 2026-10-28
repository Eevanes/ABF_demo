---
name: arena-feedback-review
description: Owner复盘点踩、重复问题、人工升级并提出知识或Skill改进建议时使用。
owner: 赛事运营Owner（待指定）
reviewer: 独立Reviewer（待指定）
version: 0.3.0
status: draft
allowed_roles:
- admin
tools:
- list_feedback
- list_tickets
- propose_change
inputs: feedback_id, summary, issue_url?
output_schema: proposal_id, feedback_id, status=proposed, issue_url?
sources:
- Arena MCP tool results
- Git-managed approved policy release
escalation: 人工Owner；投递未确认则明确待处理
failure_modes: forbidden / unknown_feedback / reviewer_pending
eval_cases:
- feedback-admin-only
- feedback-draft-only
---

1. 仅Owner/Admin调用 list_feedback 和 list_tickets 聚类失败与重复异常。
2. 选取真实feedback_id，区分补知识、改Skill、修数据、修代码和人工裁决。
3. propose_change 只保存 proposed 草稿；外部Issue链接仅在确已创建后填写。
4. 交Reviewer审批、跑固定Evals、记录发布版本和回滚点；完成前保持待发布。

---
name: answer_rules
roles: [participant, staff, admin]
tools: [search_knowledge, escalate]
when: 询问比赛规则或提交规范
---
规则只依据 search_knowledge 返回的原文，并注明来源。无依据或涉及争议就转人工。

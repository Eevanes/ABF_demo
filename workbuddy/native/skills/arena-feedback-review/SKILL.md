---
name: arena-feedback-review
description: Owner 复盘反馈、重复问题和异常工单，并提出知识、Skill、代码或数据修改时使用。
version: 0.4.0
status: candidate
allowed_roles: [admin]
---

1. 核对 [能力绑定](../../CAPABILITIES.md)，通过按角色隔离的原生表格读取反馈与工单；管理员权限未在底层验证时使用独立认证的兼容接口或停止读取。
2. 对真实反馈编号分类：知识／Skill／代码／数据／人工裁决。输出问题、证据、影响、修改草案和对应回归用例；使用匿名摘要。
3. 草案通过受控 `propose_change` 保存；只有确已创建的外部链接才作为证据。不将草案或一次模型建议标记为正式发布。
4. 记录 Owner/Reviewer 审核、测试结果、发布 commit 与回退点；使用同一原问题在企微渠道复测，填写改善结果。

完成标准：至少一个真实问题完成反馈、审核、修改、发布和回归。真实用例：F01、F02。

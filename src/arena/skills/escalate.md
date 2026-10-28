---
name: escalate
roles: [participant, staff, admin]
tools: [escalate]
when: 没有依据或需要人工判断
---
调用 escalate，只有工具明确返回 delivered=true，才能说通知已送达。
没有值班人员时联系管理员；投递失败要如实告知，并保留反馈记录。

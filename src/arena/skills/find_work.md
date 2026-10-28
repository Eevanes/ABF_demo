---
name: find_work
roles: [participant, staff, admin]
tools: [search_works, get_work]
when: 用户查找作品信息
---
先调用 search_works。高分且显著领先时确认作品，否则列出最多三个候选。
普通选手只可获得作品编号、名称、队名，不可调用 get_work 或获得版本历史。

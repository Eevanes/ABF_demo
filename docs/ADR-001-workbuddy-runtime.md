# ADR-001：WorkBuddy 接入方式

状态：桌面本机公共只读PoC及企微私聊闭环通过，正式运行模式待决策。日期：2026-10-28。

工作人员链路为企业微信 → WorkBuddy 原生渠道 → Arena 工作人员 MCP。
第一轮只开放公共只读查询。用户于2026-10-28明确选择沿用原`test机器人`，由WorkBuddy接管；不新建或修改机器人资料及历史。桌面版仅做单用户演练；正式运行优先评估 Enterprise。
不新增自建消息 Gateway，除非原生渠道的身份、会话或回执无法满足要求。

工作人员 MCP 默认不读取企微原机器人配置，不启动旧机器人，也不抢占其长连接。
当前机器 WorkBuddy 已安装，启动后曾出现窗口但随即退出，未能读取账号/席位状态。
这次启动不构成 WorkBuddy 接入成功的证据。
后续复核已发现持续运行的WorkBuddy进程，恢复最小化窗口后主界面正常加载；此前退出观察不再作为当前阻塞。
本机MCP连接配置已通过界面保存，用户完成首次信任后，真实Hy3模型查询作品及匿名详情拒绝均通过；详见 docs/v03-workbuddy-local-acceptance.json。

用户已完成原`test机器人`的WorkBuddy授权及企微桌面安全验证。本机未发现旧8765服务可达，Python进程仅有当前工作人员MCP；没有执行停止旧进程操作。20:42用户在原机器人私聊发送只读测试，收到H-001/RAG知识助手及内部详情拒绝回复；后台20:42:36和20:42:42记录两次CallToolRequest，企业微信回复已由界面读回并经用户确认。该本机原生渠道不需要公网MCP；详见 docs/v03-wecom-acceptance.json。

待验收：群 @、不同员工会话隔离、可验证 sender 身份到 MCP、异常退出恢复、费用与云端外网可达性。
上述身份链路不通过时，仅允许公共查询；不能把一个共享 staff 凭据当成每位聊天发送者的身份。

依据：[企微接入指南](https://www.workbuddy.cn/docs/workbuddy/Wecom-Guide)、
[企业版说明](https://cloud.tencent.com/document/product/1831/138968)、
[原迭代方案](https://app.notion.com/p/407a4d98cffb81229afdfcafdfa0010b)。官方能力说明不等于本机验收。

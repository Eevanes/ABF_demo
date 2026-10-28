# ADR-001：WorkBuddy 接入方式

状态：代码准备完成，运行模式待真实 PoC 决策。日期：2026-10-28。

工作人员链路为企业微信 → WorkBuddy 原生渠道 → Arena 工作人员 MCP。
第一轮只开放公共只读查询，使用独立测试机器人。桌面版仅做单用户演练；正式运行优先评估 Enterprise。
不新增自建消息 Gateway，除非原生渠道的身份、会话或回执无法满足要求。

工作人员 MCP 默认不读取企微原机器人配置，不启动旧机器人，也不抢占其长连接。
当前机器 WorkBuddy 已安装，启动后曾出现窗口但随即退出，未能读取账号/席位状态。
这次启动不构成 WorkBuddy 接入成功的证据。
后续复核已发现持续运行的WorkBuddy进程，恢复最小化窗口后主界面正常加载；此前退出观察不再作为当前阻塞。
本机MCP连接配置已通过界面保存，用户完成首次信任后，真实Hy3模型查询作品及匿名详情拒绝均通过；详见 docs/v03-workbuddy-local-acceptance.json。企微消息渠道尚未联调。

待验收：独立测试 Bot、单聊/群 @、不同员工会话隔离、可验证 sender 身份到 MCP、异常退出恢复、费用与外网可达性。
上述身份链路不通过时，仅允许公共查询；不能把一个共享 staff 凭据当成每位聊天发送者的身份。

依据：[企微接入指南](https://www.workbuddy.cn/docs/workbuddy/Wecom-Guide)、
[企业版说明](https://cloud.tencent.com/document/product/1831/138968)、
[原迭代方案](https://app.notion.com/p/407a4d98cffb81229afdfcafdfa0010b)。官方能力说明不等于本机验收。

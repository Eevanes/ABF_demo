# ADR-003：MCP 权限及身份

状态：独立凭据机制已实现，WorkBuddy sender 透传待验收。日期：2026-10-28。

选手 MCP 默认 localhost:8765/mcp；工作人员 MCP 默认 localhost:8766/mcp。
选手工具仍通过队伍 Bearer 识别本队，工具参数不提供可修改的 work_id。
工作人员凭据来自独立环境映射 ARENA_STAFF_CREDENTIALS，其中只有 token_sha256、userid、role 和可选 work_ids。
工作范围按服务端身份映射校验；聊天文本、模型参数、X-User-Id 等自报信息不是可信身份。

未配置凭据时只提供公共查询；错误 Bearer 返回 401，不能降级为已认证工作人员。
内部 SOP、版本详情与值班查询要求真实独立认证身份；选手队伍密钥不能调用工作人员工具。
有副作用工具还需显式写开关及已装配工单服务，高风险管理工具不在此入口开放。

独立 Bearer 是可供本地协议演练的认证代理，不等于已验证 WorkBuddy 原生企微 sender 透传。
任何多人共享 WorkBuddy 会话不得配置通用 staff/admin Token 后宣称按用户隔离；先做公共只读 PoC。
撤销或轮换凭据后重启工作人员服务；旧 Token 随之失效。日志不记录认证头。

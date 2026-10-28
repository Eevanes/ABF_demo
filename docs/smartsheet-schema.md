# SmartSheetRegistry v0.3

`src/arena/adapters/smartsheet_registry.py` 的 `SCHEMA` 是五表字段契约。
现有 v0.2 四表可只读查询；v0.3 写路径要求新增字段和第五张工单表全部读回通过。
适配器不自动修改既有表，`verify_schema()` 仅检查字段名称。

- 作品表：沿用作品ID、名称、队伍、成员、别名、简介、最新版本、状态、仓库链接。
- 版本表：增加 `submission_id`、`registration_status`、`policy_version`、仓库链接。
- 值班表：增加独立 `duty_id`、`backup_userid`、`status`，开始/结束时间带业务时区。
- 反馈表：增加 interaction/ticket/policy/skill/Issue 关联及来源、问题类别、拒答、处理人。
- 工单表：唯一 ticket_id/request_id/request_hash、唯一负责人、状态、证据、通知回执、时间和说明。

作品ID、最新版本、版本 SHA/tag、幂等字段由 Arena 管理；别名和排班等人工字段由运营维护。
真实表格的列/用户权限必须由管理员在企微配置后实际验收；代码白名单不等于平台列权限。
队伍凭据或哈希不进入五表。`SmartSheetRegistry.authenticate()` 先调用独立凭据源，
再读云端作品状态，禁用立即生效。`EnvironmentCredentials` 仅读本机环境哈希，不镜像业务记录。

提交依次创建 registration_pending 版本、更新作品最新指针、将版本改为 registered。
重复 submission_id/tag 且 SHA/hash 相同则只补写；冲突拒绝；历史补写不会回退最新指针。
表 API 无事务和原子 CAS。正式部署必须保持单进程/跨进程租约，不能将本适配器直接扩成多副本并发写。
网络超时和无写入回执均保留待恢复状态；人工核对冲突，不强制覆盖。

读取不使用缓存，因此人工排班修改在下一次读取时生效；重叠班次会阻断自动分配并要求复核。
原生 `date_time` 无时区字符串按 Asia/Shanghai 解释。新 timestamp 文本保存 ISO 时区。
空表成功响应可能省略 records；适配器按空集合处理。检查列表和证据列表采用 `json:` 前缀
结构化文本，防止 CLI 将裸 JSON 数组规范化成普通文本；旧版单条检查说明仍可读取。

`scripts/v03_smartsheet_acceptance.py` 默认仅输出 dry run；`--execute` 新建独立沙盒、
写虚构数据并真实读回。它不会修改 `SMARTSHEET_DOCID` 或旧表；沙盒 ID 仅保存本地用户环境
`ARENA_V03_SMARTSHEET_DOCID`。报告只保存去标识后的断言结果。
该验收只证明表格适配器，不代表 GitHub App 作品写入、WorkBuddy、企微通知或正式赛时验收。

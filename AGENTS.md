# Arena demo

- 面向用户用简体中文，区分本地验证、接口候选与真实联调。
- 用户原始方案在 README 来源链接。当前范围见 README 的差距章节，不把 demo 说成 M1–M8 全量验收。
- 所有凭据只通过本机环境变量传入；不得输出、上传、写入明文文件或记忆。
- 不覆盖用户原有企业微信文档、数据、权限、机器人和 GitHub 内容。
- 测试默认无外网，仅 localhost TCP。外部系统只有在明确配置并具备作用域后才联调。
- `uv run pytest -q`、`uv run ruff check .`、`uv run mypy src` 是相关验证命令。
- `src/arena/knowledge` 为示例规则，`src/arena/skills` 为可加载的技能；真实办赛前必须由主办方替换。

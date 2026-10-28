# 示例提交规范（待主办方替换）

## 怎么提交作品
通过 MCP 的 submit_work 提交 UTF-8 文本或 base64 文件，根目录必须有 README.md。
README 应说明作品用途、运行方法与依赖。README 少于 200 字时会给出提示。
默认文件总大小不超过 5MB。相同内容不能重复提交，每个版本自动生成 tag。
凭据不得提交：请移除 .env、真实 API Key 和私钥。

## 查询自己的版本
调用 get_my_work 查看本队编号和最新版本，调用 list_my_versions 查看本队历史。
本地 demo 暂不接收 repo_url，不能将它当成大仓库上传方案。

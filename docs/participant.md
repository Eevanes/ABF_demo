# 选手接入（本地 demo）

三个工具：`get_my_work` 查询自己的编号与最新版本；`submit_work` 提交文件；`list_my_versions` 查询历史。

示例参数（内容无凭据）：

```json
{
  "description": "首版：完成作品主体和运行说明。",
  "files": [
    {"path": "README.md", "content": "# 我的作品\n用途、依赖、运行步骤……", "encoding": "utf-8"},
    {"path": "src/app.py", "content": "print('demo')", "encoding": "utf-8"}
  ]
}
```

不填写作品编号。服务根据队伍密钥识别身份。默认总大小 5MB，根目录必须有 README.md；目录整体替换，删除的旧文件不会残留；不可提交真实凭据。

当前仅验证本地官方 MCP 客户端的真实 HTTP 协议；尚未在 Claude Code / Cursor 中完成公网远程接入。为避免将队伍密钥写入配置文件，此版使用进程环境中的密钥完成自动协议演练。正式客户端如何安全传入认证头需接入时确认。

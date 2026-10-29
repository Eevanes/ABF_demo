# 选手接入

三个工具：`get_my_work` 查询自己的编号与最新版本；`submit_work` 提交文件；`list_my_versions` 查询历史。

示例参数（内容无凭据）：

```json
{
  "submission_id": "example-request-0001",
  "description": "首版：完成作品主体和运行说明。",
  "files": [
    {"path": "README.md", "content": "# 我的作品\n用途、依赖、运行步骤……", "encoding": "utf-8"},
    {"path": "src/app.py", "content": "print('demo')", "encoding": "utf-8"}
  ]
}
```

不填写作品编号。服务根据队伍密钥识别身份。默认总大小 5MB，根目录必须有 README.md；目录整体替换，删除的旧文件不会残留；不可提交真实凭据。

当前仅验证本地官方 MCP 客户端的真实 HTTP 协议；尚未在 Claude Code / Cursor 中完成公网远程接入。为避免将队伍密钥写入配置文件，此版使用进程环境中的密钥完成自动协议演练。正式客户端如何安全传入认证头需接入时确认。

每次新提交生成新的 `submission_id`；网络错误时保持该编号、文件、标题和说明重试。同编号不同内容会拒绝，同编号已完成请求返回原版本。收到“Git 已保存，登记失败”后先查 `list_my_versions`，由运营执行 `arena reconcile`；不要改编号反复上传。

成功后核对作品编号、版本号、tag、commit SHA 和作品链接。只有 GitHub、智能表格和本队版本查询一致才算真实云端提交成功。v0.4 的两队两版联调步骤见 [提交验收](v04-submission-e2e-acceptance.md)。

远程地址应由赛事方提供经 TLS 和真实远程客户端验证的 HTTPS `/mcp` 入口。队伍 Bearer 从客户端受保护的环境变量传入 Authorization，不写进仓库 JSON、启动命令参数或聊天；各客户端的安全环境变量展开方式需在实际版本中验证，不能直接复制带明文凭据的配置。

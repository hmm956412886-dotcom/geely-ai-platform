# CoreTest Copilot 集成

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\integrations\coretest\install.ps1
```

脚本把 Qt 连接器复制到客户仓库，并对 `MainWindow` 增加最小入口。启动 CoreTest 后右侧自动出现 Copilot；设置
`AI_MODEL_BASE_URL`、`AI_MODEL_API_KEY` 和 `AI_MODEL_NAME` 后可对话并基于上传文件生成 pytest 代码。

连接器只读取项目、Trace、DBC 和诊断日志，不包含 CAN 发送、回放启动、UDS 执行或刷写入口。

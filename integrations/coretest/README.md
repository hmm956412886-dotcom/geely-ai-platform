# CoreTest Agent 集成

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\integrations\coretest\install.ps1
```

脚本把 Qt 连接器复制到客户仓库，并对 `MainWindow` 增加最小入口。启动 CoreTest 后右侧自动出现 Agent；
模型 Base URL、API Key 和模型名可从底部“API”入口配置。OpenCode Runtime 由 Connector 自动管理，无需用户配置
命令或单独启动，随后可读取已注册工程、分析附件和当前对象，并在用户逐次批准后写入和运行 pytest 测试。
PDX 分析复用 `odxtools==11.4.1`；CoreTest 构建环境必须安装该依赖。

连接器只读取项目、Trace、DBC 和诊断日志，不包含 CAN 发送、回放启动、UDS 执行或刷写入口。

生成包含独立 AI Gateway Sidecar 的 CoreTest 交付 ZIP：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build-coretest-delivery.ps1
```

交付机解压后，将 `ai-gateway/.env.example` 复制为 `ai-gateway/.env` 并填写模型配置即可启动。

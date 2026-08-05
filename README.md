# Geely AI Platform

嵌入 HK CoreTest 右侧的本地工作区智能体。目标体验对齐 Codex/Claude Code：Agent 获得当前工程这个
唯一用户工程后，可以自行搜索和读取项目、理解架构，并直接生成或修改工程文件、运行命令和验证结果。

产品使用 `QDockWidget + QWebEngineView`、AI Gateway 和 OpenCode 官方 Web UI 的 CoreTest Profile；
旧 React/assistant-ui 界面只保留为回退。工作区 Agent Runtime 采用 MIT 许可的 [OpenCode](https://github.com/anomalyco/opencode)。
客户交付不采用滚动更新或来源不明的二进制；版本锁和第三方许可证门禁见
[OpenCode 源码构建与开源合规](docs/14-open-source-compliance.md)。

## 当前产品能力

- CoreTest 原生右侧 Agent，可显示、隐藏、移动停靠位置和调整宽度。
- 普通问答、附件分析、当前对象分析和测试工作统一由 OpenCode 完成。
- OpenCode Sidecar 可在唯一注册工作区内自行搜索和读取工程，无需逐个上传文件。
- 当前项目、页面、DBC 节点/帧、Trace 帧和诊断 ECU 自动同步到独立宿主会话。
- 在工程树选中 PDX 后，使用开源 `odxtools` 解析 ECU、诊断层、服务和 CAN 通信参数并直接分析。
- 支持有真实历史的多轮对话和与当前工程关联的新建对话。
- Trace、DBC、诊断日志和 PDX 由宿主提供确定性事实，再交给 OpenCode 分析。
- Agent 可通过内置 `coretest-host` 命令主动查询 CoreTest 已解析的工程、文件、DBC、Trace 和诊断数据，不需要用户先点击对应功能；该桥只读且仅监听本机。
- AI Gateway Sidecar 生命周期、分级 Bearer Token、OpenAPI、Plugin Manifest 和审计 `request_id`。
- OpenCode 使用客户配置的 OpenAI-compatible Provider 调用模型。

当前权限模型为：CoreTest、CoreTest Agent 和 Gateway 产品源码永久只读；OpenCode 只操作可信 Connector 注册的当前用户工程，
工程内读写文件和 Shell 命令自动允许；OpenCode 文件/Web 工具拒绝工作区外目录和 Web 访问，CAN、UDS、刷写、设备控制不向 Agent 暴露。正式包还需用安装目录 ACL 约束 Shell 子进程，当前不是操作系统级强沙盒。

用户只需启动一次 CoreTest。CoreTest 内部常驻一个隐藏 Gateway；OpenCode 在第一次真正使用 AI 时按需启动，
同一工程的后续对话复用该进程，退出 CoreTest 时先关闭 OpenCode 再关闭 Gateway。极狐完整 CoreTest 仓库和正式客户包
内置经过 SHA-256 校验的锁定版 OpenCode，运行时不会再下载；用户只需在侧栏配置模型 API。

## 当前交付目标

当前已完成 OpenCode Runtime、离线内置、按需启动、可信用户工程注册、产品源码保护、原生 Web UI 安全代理、模型配置映射和 `coretest-host` 只读能力桥；
侧栏会根据 OpenCode 的真实快照能力启用撤销，并明确提示非 Git 工程的修改无法自动撤销。测试请求已改为
Agent 在用户工程中自动写入并运行最小相关测试，不再只是返回代码供下载。真实模型验收需要验证 Agent 能读取项目说明、调用现有 CLI、
自动创建测试并运行测试，同时不能修改产品源码。正式交付已锁定 OpenCode 版本、ZIP/EXE 哈希并生成 CycloneDX SBOM、
MIT License 和第三方 Notices；下一步是用真实模型复验 Host 能力调用、用户工程修改、测试、Diff 和撤销，并完成客户侧验收。具体边界和验收标准以
[产品开发计划](docs/13-reusable-ai-plugin-development-plan.md) 为准。

## 配置模型

侧栏“模型与 API”使用 OpenCode 原生 Provider 管理，可添加、删除和切换多套 API 与模型。首次启动仍兼容以下
环境变量，并自动导入为默认 Provider：

```powershell
$env:AI_MODEL_BASE_URL='https://api.example.com/v1'
$env:AI_MODEL_API_KEY='客户自己的Key'
$env:AI_MODEL_NAME='模型名'
```

后续配置由 OpenCode Config/Auth 持久化，API Key 不会回显。未注册工作区、未配置模型或未安装 OpenCode 时，
AI 接口返回明确的 Agent Runtime 错误；测试数据摘要、比较等非 AI 数据接口仍可用。

## 启动产品

安装 CoreTest 连接器：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\integrations\coretest\install.ps1
```

随后从客户仓库启动 CoreTest，连接器会自动启动本地 Gateway 并显示右侧 CoreTest Agent。只看 Web 产品：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-ai-gateway.ps1
```

```text
http://127.0.0.1:8765/agent-native/
http://127.0.0.1:8765/copilot-shell/   # 旧版回退
http://127.0.0.1:8765/showcase
http://127.0.0.1:8765/plugin-manifest.json
http://127.0.0.1:8765/openapi.json
```

生成包含 CoreTest、Qt WebEngine 和独立 AI Gateway Sidecar 的交付 ZIP：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build-coretest-delivery.ps1
```

## 验证

```powershell
cd D:\geely-ai-platform\src\ai-gateway
$env:PYTHONPATH='src'
python -m unittest discover -s tests -p "test_*.py"
python evals\run_eval.py

cd D:\geely-ai-platform\frontend\copilot-shell
pnpm typecheck
pnpm build

cd D:\geely-ai-platform\samples\host-integration
python -m unittest discover -s . -p "test_*.py"

cd D:\geely-ai-platform\integrations\coretest
$env:PYTHONPATH='.'
python -m unittest discover -s tests -p "test_*.py"
```

## 有效文档

- [产品开发计划](docs/13-reusable-ai-plugin-development-plan.md)
- [开发与验收指南](docs/04-development-guide.md)
- [客户部署指南](docs/12-customer-deployment-guide.md)
- [CoreTest 集成](integrations/coretest/README.md)
- [OpenCode 源码构建与开源合规](docs/14-open-source-compliance.md)

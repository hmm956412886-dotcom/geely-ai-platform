# Geely AI Platform

嵌入 HK CoreTest 右侧的本地工作区智能体。目标体验对齐 Codex/Claude Code：Agent 获得当前工程这个
唯一工作区后，可以自行搜索和读取项目、理解架构、生成代码，并在用户审批后修改文件或运行命令。

现有 `QDockWidget + QWebEngineView`、React、assistant-ui、Fluent UI 和 AI Gateway 继续作为产品外壳；
工作区 Agent Runtime 采用 MIT 许可的 [OpenCode](https://github.com/anomalyco/opencode)。
客户交付不采用滚动更新或来源不明的二进制；版本锁和第三方许可证门禁见
[OpenCode 源码构建与开源合规](docs/14-open-source-compliance.md)。

## 当前产品能力

- CoreTest 原生右侧 Copilot，可停靠、显示、隐藏和调整宽度。
- 普通问答、附件分析、当前对象分析和 pytest 生成统一由 OpenCode 完成。
- OpenCode Sidecar 可在唯一注册工作区内自行搜索和读取工程，无需逐个上传文件。
- 当前项目、页面、DBC 节点/帧、Trace 帧和诊断 ECU 自动同步到独立宿主会话。
- 在工程树选中 PDX 后，使用开源 `odxtools` 解析 ECU、诊断层、服务和 CAN 通信参数并直接分析。
- 支持有真实历史的多轮对话和与当前工程关联的新建对话。
- Trace、DBC、诊断日志和 PDX 由宿主提供确定性事实，再交给 OpenCode 分析。
- AI Gateway Sidecar 生命周期、分级 Bearer Token、OpenAPI、Plugin Manifest 和审计 `request_id`。
- OpenCode 使用客户配置的 OpenAI-compatible Provider 调用模型。

当前权限模型为：工作区内读取允许；写文件和 Shell 命令逐次审批；工作区外访问和 CAN、UDS、刷写、
设备控制始终禁止。

用户只需启动一次 CoreTest。CoreTest 内部常驻一个隐藏 Gateway；OpenCode 在第一次真正使用 AI 时按需启动，
同一工程的后续对话复用该进程，退出 CoreTest 时先关闭 OpenCode 再关闭 Gateway。Windows 源码运行首次使用
会下载并校验锁定版本，之后复用本机缓存；正式客户包应内置审核通过的同一二进制。

## 当前交付目标

当前已完成 OpenCode Runtime、按需启动、可信工作区注册、模型配置映射、工具活动、权限审批及 Diff/revert；
下一步接入 SSE 实时回答和命令输出。具体边界和验收标准以
[产品开发计划](docs/13-reusable-ai-plugin-development-plan.md) 为准。

## 配置模型

使用任意支持可靠工具调用的 OpenAI-compatible API：

```powershell
$env:AI_MODEL_BASE_URL='https://api.example.com/v1'
$env:AI_MODEL_API_KEY='客户自己的Key'
$env:AI_MODEL_NAME='模型名'
```

这些值会映射到 OpenCode 的 OpenAI-compatible Provider。未注册工作区、未配置模型或未安装 OpenCode 时，
AI 接口返回明确的 Agent Runtime 错误；测试数据摘要、比较等非 AI 数据接口仍可用。

## 启动产品

安装 CoreTest 连接器：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\integrations\coretest\install.ps1
```

随后从客户仓库启动 CoreTest，连接器会自动启动本地 Gateway 并显示右侧 Copilot。只看 Web 产品：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-ai-gateway.ps1
```

```text
http://127.0.0.1:8765/copilot-shell/
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

# Geely AI Platform

可嵌入 HK CoreTest、其他桌面软件和网站的 AI Copilot。当前产品已经在真实 CoreTest 主窗口中提供右侧
`QDockWidget + QWebEngineView`，复用 React、assistant-ui 和 Fluent UI，并通过稳定的 AI Gateway REST API
连接宿主上下文、文件、模型和分析工具。

## 当前产品能力

- CoreTest 原生右侧 Copilot，可停靠、显示、隐藏和调整宽度。
- 普通模型问答；添加代码、配置、DBC、ASC 等文本文件后可基于内容提问。
- 基于附件生成完整 pytest 测试模块，在对话中预览、复制并明确保存到当前项目 `generated_tests`。
- 当前项目、页面、DBC 节点/帧、Trace 帧和诊断 ECU 自动同步到独立宿主会话。
- Trace、DBC、诊断日志和项目文件的确定性只读分析。
- AI Gateway Sidecar 生命周期、分级 Bearer Token、OpenAPI、Plugin Manifest 和审计 `request_id`。
- 可选 Semantic Kernel 单 Agent 只读工具编排和飞书 CLI 知识查询。

不会自动执行生成代码，不修改客户业务源码、测试配置或数据库，也不发送 CAN、启动回放、执行 UDS 或刷写 ECU。

## 配置模型

使用任意 OpenAI-compatible API：

```powershell
$env:AI_MODEL_BASE_URL='https://api.example.com/v1'
$env:AI_MODEL_API_KEY='客户自己的Key'
$env:AI_MODEL_NAME='模型名'
```

未配置模型时，Trace/DBC/诊断确定性分析仍可用；对话和测试代码生成会返回明确错误，不会伪造模型结果。

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

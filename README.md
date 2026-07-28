# Geely AI Platform

面向测试软件的通用 AI 插件底座。当前策略是先做可展示、可嵌入、可替换模型 API 的产品 MVP，再逐步接入成熟开源 Copilot 前端、真实飞书知识库、测试数据文件和 Agent 编排。

主开发计划见：[可复用 AI 插件完整开发计划](docs/13-reusable-ai-plugin-development-plan.md)。

## 当前方向

先交付一个外置 AI Gateway，而不是一开始就深度改造客户软件。

```text
客户测试软件
  -> WebView / iframe / HTTP / CLI / 文件路径
  -> AI Gateway
  -> 知识源：飞书 CLI
  -> 数据源：测试软件导出文件、PDX Adapter、客户 API
  -> 模型 API：客户自行配置
```

白话备注：先让客户软件或公司网站能嵌入同一个 AI 面板，或调用同一个本地 HTTP 服务。后面客户换 API Key、换模型、换知识库，都不需要改宿主软件主体逻辑。

## MVP 先做什么

1. AI Gateway 可启动。
2. `/showcase` 可展示宿主软件 + Copilot 的完整产品形态。
3. `/api/v1/analyze` 可被宿主软件或插件按钮调用。
4. `/plugin-manifest.json` 描述宿主软件如何集成。
5. `/api/v1/tools` 描述 Agent / SK 可调用的工具契约。
6. `/openapi.json` 描述 HTTP API。
7. 飞书先通过 CLI 查询，不做全量迁移。
8. 测试数据先通过 JSON fixture 或文件 Adapter 接入，不猜 PDX 内部格式。
9. `samples/host-integration` 提供无源码集成样例和 Python Host SDK 样板。
10. `/copilot-shell/` 作为 React + assistant-ui + Fluent UI 可复用侧边栏，`/showcase` 只负责演示嵌入效果。
11. `/api/v1/test-data/insights` 提供确定性数据洞察，优先用 DuckDB，未安装时回退标准库。
12. `scripts/start-ai-gateway.ps1` 和 `scripts/check-ai-gateway.ps1` 提供客户部署启动与验收入口。
13. 宿主通过 `host_session_id`、`postMessage` 和 `asset_id` 安全复用同一个 Copilot。
14. `scripts/start-copilot-shell.ps1` 可独立启动前端联调服务，检查脚本可同时验证 Gateway 和前端 URL。
15. P0 产品底座和演示交付已完成；Semantic Kernel 只读工具编排和可选 Gateway Bearer 鉴权已跑通。
16. 设置 `AI_KNOWLEDGE_PROVIDER=feishu-cli` 后，Gateway 可返回当前用户有权限的真实飞书文档片段和引用链接。
17. 设置 `AI_GATEWAY_ACCESS_TOKEN` 后，所有 `/api/v1/*` 请求必须携带 Bearer Token；未设置时保留本机离线演示。

暂不做：动态 UI、多 Agent、写入类工具、设备控制、全量向量库迁移、继续手写零散 Copilot UI。

## 运行 AI Gateway MVP

一键启动产品演示（Gateway 会直接提供生产构建的 Copilot）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-ai-gateway.ps1
```

独立启动前端联调服务：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-copilot-shell.ps1 -GatewayUrl http://127.0.0.1:8765
```

手动启动 Gateway：

```powershell
cd D:\geely-ai-platform\src\ai-gateway
$env:PYTHONPATH='src'
python -m ai_gateway.server --port 8765
```

打开产品展示页：

```text
http://127.0.0.1:8765/showcase
```

只看右侧 Copilot 面板：

```text
http://127.0.0.1:8765/copilot-shell/
```

查看集成契约：

```text
http://127.0.0.1:8765/plugin-manifest.json
http://127.0.0.1:8765/api/v1/tools
http://127.0.0.1:8765/openapi.json
```

测试数据洞察示例：

```powershell
Invoke-RestMethod `
  -Method Post `
  -ContentType 'application/json' `
  -Uri 'http://127.0.0.1:8765/api/v1/test-data/insights' `
  -Body '{"source_file":"D:\\geely-ai-platform\\src\\ai-gateway\\tests\\fixtures\\test-run-cases.csv"}'
```

白话备注：`insights` 是给演示和第一版集成看的“稳定数据分析按钮”。它不让大模型自己算通过率、失败分布这些关键指标，而是用代码算好，再让 Copilot 展示和解释。

## 目录结构

```text
.
├── contracts/                # OpenAPI、Plugin manifest、JSON Schema
├── config/                   # 不含密钥的配置模板
├── docs/                     # 架构、开发和集成文档
├── infra/                    # 本地基础设施配置
├── samples/                  # 宿主软件集成样例
├── scripts/                  # 启动和部署检查脚本
├── src/
│   └── ai-gateway/           # 当前产品 MVP：外置 AI Gateway
└── workers/
    └── feishu-sync/          # 飞书 CLI Provider / 可选同步 Worker
```

## 文档入口

- [优先级与第一步](docs/00-priority-and-first-step.md)
- [整体架构](docs/01-architecture.md)
- [开源项目复用方案](docs/02-open-source-reuse.md)
- [飞书知识库接入设计](docs/03-feishu-connector.md)
- [开发约定与验收标准](docs/04-development-guide.md)
- [CodeGraph 使用说明](docs/05-codegraph-usage.md)
- [MVP 无源码接入方案](docs/06-mvp-integration-without-source.md)
- [GitHub 版本控制指南](docs/07-github-versioning.md)
- [测试数据文件分析方案](docs/08-test-data-file-analysis.md)
- [产品 MVP 集成契约](docs/09-product-mvp-contract.md)
- [可复用 Copilot 嵌入契约](docs/10-reusable-copilot-embed.md)
- [MVP 交付计划](docs/11-mvp-delivery-plan.md)
- [客户部署指南](docs/12-customer-deployment-guide.md)
- [可复用 AI 插件完整开发计划](docs/13-reusable-ai-plugin-development-plan.md)

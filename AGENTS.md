# AGENTS.md

本文件约束本项目内的 AI 编码行为。目标是先做出可展示、可集成、可复用的 AI 插件底座，再逐步补真实能力。

## 0. 当前主计划

后续对话或新 AI 接手时，必须先读：

1. `docs/13-reusable-ai-plugin-development-plan.md`
2. `docs/04-development-guide.md`
3. `README.md`

当前默认下一步是：

```text
P0-018：开源 Copilot 插件底座 Spike
```

方向：不要继续手写零散 HTML 小功能。现有 AI Gateway 作为后端契约保留，前端 Copilot 插件优先调研并接入 CopilotKit；如果过重，再退回 assistant-ui。AG-UI、SK / Microsoft Agent Framework、RAG 都放在后续阶段。

## 1. 先想清楚再写代码

- 新功能先写计划、边界和验收标准，再写代码。
- 文档用于约束未来开发，不是代码完成后的补丁说明。
- 不要假设客户软件内部实现；没有源码时，以 HTTP、WebView、CLI、文件契约为准。
- 有多种理解时，先说清楚取舍。
- 不清楚 PDX 等测试文件格式时，不猜格式；优先找官方工具、SDK、CLI 或客户导出能力。
- 每个任务先定义可验收结果。

## 2. 简单优先

- 能用标准库，就用标准库。
- 有成熟开源项目或官方 SDK，就优先复用，不从 0 自研。
- 不为单次使用写抽象。
- 不提前做动态 UI、多 Agent、向量库迁移、复杂中间件。
- MVP 只保留能展示、能集成、能验证的代码。

## 3. 改动要克制

- 只改和当前任务直接相关的文件。
- 不顺手重构无关代码。
- 不提交客户真实数据、PDX、日志、密钥或本地缓存。
- `.codegraph/`、`__pycache__/`、测试大文件不进入 Git。

## 4. 产品 MVP 优先级

P0 只做：

- AI Gateway 可启动。
- `/showcase` 可展示宿主软件和 Copilot。
- `/copilot` 可作为可复用侧边栏嵌入。
- `/plugin-manifest.json` 描述插件/宿主集成方式。
- `/openapi.json` 描述 HTTP 接口。
- `/api/v1/analyze` 返回只读分析结果。
- `/api/v1/test-data/insights` 返回确定性数据洞察。
- Host SDK 样例可模拟宿主软件接入。
- 客户部署脚本可启动和检查服务。
- 飞书知识库后续通过 CLI 查询。
- 测试数据通过文件 Adapter 或 fixture 进入。

暂不做：

- 写入客户系统。
- 修改测试配置。
- 控制测试设备。
- 全量迁移飞书知识库。
- 没有真实需求的复杂插件 SDK。

## 5. 开源复用优先级

- Copilot 前端：优先 CopilotKit，过重时用 assistant-ui。
- Agent 前端协议：AG-UI 放到后续阶段，不在 P0 强上。
- 后端编排：SK / Microsoft Agent Framework 后续接 Tool Registry。
- 数据分析：DuckDB / Polars / Pandas 藏在 Adapter 后。
- RAG：飞书 CLI 跑通后再评估 LlamaIndex / Haystack / LanceDB / Qdrant。

## 6. 验证

每个非平凡改动至少运行对应测试。

常用命令：

```powershell
cd D:\geely-ai-platform\src\ai-gateway
$env:PYTHONPATH='src'
python -m unittest discover -s tests -p "test_*.py"
```

```powershell
cd D:\geely-ai-platform\workers\feishu-sync
$env:PYTHONPATH='src'
python -m unittest discover -s tests -p "test_*.py"
```

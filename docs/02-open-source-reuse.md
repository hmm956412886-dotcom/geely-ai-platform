# 开源项目复用方案

调研日期：2026-07-24

## 1. 基本判断

这个项目不要闭门造车。AI Gateway 负责统一契约、权限、审计和业务编排；成熟能力尽量用开源库、官方 SDK 或独立服务承接。

白话备注：我们自己做“插座和配电箱”，不要自己发明每一种电器。数据分析、图表、RAG、表单渲染、Agent UI 都有成熟项目，关键是别让它们反过来绑死我们的平台边界。

## 2. 推荐复用清单

| 能力 | 推荐项目 | 复用方式 | 优先级 | 备注 |
| --- | --- | --- | --- | --- |
| AI 编排 | Semantic Kernel / Microsoft Agent Framework | SDK | P0/P1 | SK 继续作为 Plugin/Function Calling 抽象；Agent Framework 作为后续多 Agent 演进方向 |
| RAG 产品参考 | RAGFlow | 独立服务或质量参考 | P1 | 文档解析、分块、引用可视化成熟；不建议直接成为公司级核心边界 |
| 低代码 AI 应用 | Dify | PoC/对照平台 | P1 | 适合快速验证工作流；许可证和多租户限制需单独评估 |
| 文档解析 | Docling / Unstructured | 独立 Parser Adapter | P1 | PDF、Office、扫描件解析优先复用 |
| 向量检索 | Qdrant / PGVector | Provider | P1 | MVP 不强依赖，真实 RAG 规模上来后接 |
| 文件级分析 | DuckDB | 查询引擎 | P0 | 可直接查询 CSV/JSON/Parquet，适合测试导出文件 |
| DataFrame 计算 | Polars / Pandas | 库 | P0 | 小中型数据先 Pandas，大文件优先 Polars/DuckDB |
| 自动数据画像 | ydata-profiling | 报告生成器 | P1 | 适合“一键看数据概况”，大数据要用 minimal/sample 模式 |
| 数据质量 | Great Expectations | 质量规则引擎 | P1 | 用于字段范围、缺失值、唯一性、阈值规则 |
| 漂移/评测监控 | Evidently | 评测/监控 | P1 | 可用于测试数据分布变化、LLM/RAG 质量指标 |
| 可视化探索 | PyGWalker / Graphic Walker | 嵌入式分析 UI | P1 | DataFrame 拖拽分析，不用自己写 BI 小工具 |
| Text-to-SQL | Vanna | 参考或可选组件 | P1 | 适合关系库自然语言查询；注意 2026-03-29 GitHub 仓库已归档 |
| Chat UI | assistant-ui | 前端组件 | P0 | React AI 对话 UI，作为 CopilotKit 过重时的回退方案 |
| Agent 前端协议 | AG-UI | 协议 | P1 | 适合后续 Agent 与前端状态/事件流对接 |
| 生成式 UI / Copilot 插件 | CopilotKit / OpenGenerativeUI | 框架/范例 | P0 | P0-018 首选 Spike；动态 UI 能力后续再打开 |
| JSON Schema 表单 | react-jsonschema-form / JSON Forms | 前端组件 | P2 | 动态表单优先走 Schema，不让模型直接写业务代码 |
| 企业低代码 | amis / Appsmith / Budibase / ToolJet | 独立平台或参考 | P2 | 适合管理台/配置台，不建议嵌入工业测试主流程 |
| 汽车诊断 PDX/ODX | odxtools | Parser 候选 | P1 | 只适用于 ODX/PDX 诊断描述类文件；测试结果 PDX 要先确认格式 |

## 3. 数据分析模块怎么复用

### 3.1 MVP：先用确定性工具

优先链路：

```text
测试软件导出文件
  -> File Adapter
  -> DuckDB / Pandas / Polars
  -> 标准 TestRunSummary JSON
  -> AI Gateway 解释
```

推荐先实现：

- CSV / JSON：用 Python 标准库或 DuckDB。
- Excel：后续用 openpyxl / pandas。
- Parquet：DuckDB 或 Polars。
- PDX：先用官方工具或 odxtools 做 Spike，不猜格式。

白话备注：AI 不负责算通过率，AI 负责解释通过率。通过率、失败数、阈值超限这些应由确定性代码算出来。

### 3.2 P1：再补分析增强

- ydata-profiling：生成数据画像报告。
- Great Expectations：做数据质量规则，比如“扭矩误差必须小于阈值”。
- Evidently：做两批测试数据的分布变化、漂移和回归检查。
- PyGWalker：提供拖拽式探索分析界面。
- Vanna：如果客户开放关系数据库且允许 SQL 查询，再评估 Text-to-SQL。

## 4. 一句话生成 UI 怎么复用

这里要分三层，不能混在一起。

### 4.1 安全可控：JSON Schema 驱动 UI

适合：

- 参数表单。
- 过滤条件。
- 测试报告配置。
- 只读数据详情页。

推荐：

- react-jsonschema-form。
- JSON Forms。

做法：

```text
用户自然语言
  -> LLM 生成 JSON Schema / UI Schema
  -> 后端校验 Schema
  -> 前端组件渲染
  -> 用户确认
```

白话备注：模型只生成“界面说明书”，不直接生成能操作设备的代码。

### 4.2 Agent UI：事件协议和工具渲染

适合：

- AI 分析过程流式展示。
- 工具调用结果展示。
- 人工确认。
- 多步骤任务。

推荐：

- assistant-ui：快速做 React 对话界面。
- AG-UI：后续统一 Agent 与前端之间的事件协议。
- CopilotKit：前端 Copilot、Generative UI、人机协同。

### 4.3 开放式生成 UI：必须放到沙箱

适合：

- 临时图表。
- 临时数据探索组件。
- 算法演示。
- 报告中的交互式小组件。

推荐参考：

- CopilotKit/OpenGenerativeUI。

要求：

- iframe 沙箱。
- 禁止访问本地文件和客户内网。
- 禁止直接调用写入类 API。
- 生成结果必须可预览、可撤销、可确认。

白话备注：一句话生成 UI 可以做，但第一版只能生成“可看、可点、可丢弃”的临时界面，不要一上来生成正式生产模块。

## 5. 复用边界

AI Gateway 内部只保留这些稳定接口：

```text
KnowledgeProvider
TestDataAdapter
AnalysisEngine
UiSchemaGenerator
ToolRegistry
AuditLogger
```

第三方库全部包在 Adapter 后面：

```text
DuckDB / Polars / ydata-profiling / Great Expectations
  -> TestDataAdapter 或 AnalysisEngine
  -> 标准 JSON
  -> AI Gateway
```

这样后面换库不影响宿主软件。

## 6. 不建议做的事

- 不自研 DataFrame。
- 不自研图表库。
- 不自研向量数据库。
- 不自研通用低代码平台。
- 不让 LLM 直接生成并执行客户软件插件代码。
- 不让 Text-to-SQL 直接查生产库，至少要只读账号、白名单、行级权限和 SQL 审计。

## 7. 下一步开发建议

P0 下一步先接入开源 Copilot 插件底座，而不是继续手写前端小功能：

1. 建 `frontend/copilot-shell`。
2. 优先 Spike CopilotKit。
3. 如果 CopilotKit 过重或侵入太强，退回 assistant-ui。
4. 先调用现有 AI Gateway REST API，不重写后端。
5. 跑通嵌入 `/showcase` 或给出清晰替换路径。

文件分析链路已具备 JSON / CSV / insights / compare 的 MVP 基线。后续只有在客户给 Excel、PDX 样例或真实测试导出格式后，才继续扩展 TestDataAdapter。

动态 UI 方向仍然保留，但不进入 P0：

```text
POST /api/v1/ui/schema
```

但先不实现复杂前端，只返回可校验 JSON Schema 草案即可。

## 8. 参考链接

- Semantic Kernel：https://github.com/microsoft/semantic-kernel
- Kernel Memory：https://github.com/microsoft/kernel-memory
- RAGFlow：https://github.com/infiniflow/ragflow
- Dify：https://github.com/langgenius/dify
- DuckDB Python：https://duckdb.org/docs/stable/clients/python/overview
- Polars：https://pola.rs/
- ydata-profiling：https://docs.profiling.ydata.ai/
- Great Expectations：https://github.com/great-expectations/great_expectations
- Evidently：https://github.com/evidentlyai/evidently
- PyGWalker：https://pypi.org/project/pygwalker/
- Vanna：https://github.com/vanna-ai/vanna
- react-jsonschema-form：https://github.com/rjsf-team/react-jsonschema-form
- JSON Forms：https://jsonforms.io/
- assistant-ui：https://github.com/assistant-ui/assistant-ui
- AG-UI：https://github.com/ag-ui-protocol/ag-ui
- CopilotKit：https://github.com/CopilotKit/CopilotKit
- OpenGenerativeUI：https://github.com/CopilotKit/OpenGenerativeUI
- odxtools：https://pypi.org/project/odxtools/

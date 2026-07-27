# 优先级与第一步

> 当前主计划以 [可复用 AI 插件完整开发计划](13-reusable-ai-plugin-development-plan.md) 为准。本文保留早期判断和背景，不再作为下一步开发顺序的唯一依据。

## 1. 先回答“是不是需要从零做”

不需要。

但也不建议直接把 Dify、RAGFlow 或其他完整产品当成最终业务底座。更合理的方式是：

```text
复用成熟的底层能力
  + 自己定义跨系统契约
  + 自己控制权限、审计和业务 Plugin
```

建议复用：

| 能力 | 复用对象 |
| --- | --- |
| AI 编排 | Semantic Kernel |
| 后续 Agent / Workflow | Microsoft Agent Framework |
| 飞书文档读取参考 | LangChain LarkSuite Loader / 飞书官方 API |
| 向量检索 | Qdrant 或 PGVector |
| 文档解析 | Docling、Unstructured 或 RAGFlow 的解析能力 |
| 文件数据分析 | DuckDB、Pandas、Polars |
| 数据画像 | ydata-profiling |
| 数据质量 | Great Expectations |
| 数据漂移/评测 | Evidently |
| 可视化探索 | PyGWalker / Graphic Walker |
| 动态表单 UI | react-jsonschema-form / JSON Forms |
| Agent UI | assistant-ui / AG-UI / CopilotKit |
| 队列和缓存 | Redis |
| 原文和附件 | MinIO / S3 兼容对象存储 |
| 观测 | OpenTelemetry |

不建议直接复用完整产品作为核心业务边界：

- Dify：适合工作流和应用原型，但 Plugin Contract、权限和业务域仍需自己治理。
- RAGFlow：适合 RAG 引擎，但不应代替测试软件的业务服务。
- AnythingLLM / Open WebUI：适合演示，不适合作为公司级 AI 平台的唯一底座。

## 2. 优先级排序

### 当前不足

当前 MVP 已能展示 Copilot、Host Context、文件分析、对比、模型配置、错误响应、自检和进程内审计，但还不是可直接交付的生产版。主要不足：

1. 测试数据仍以 JSON/CSV fixture 为主，真实 PDX/Excel/客户 API 未接入。
2. 飞书真实知识查询暂缓，当前回答仍使用演示引用。
3. Copilot UI 是无依赖静态页，适合验证集成，不是最终体验。
4. Audit Log 和 Host Context 都是进程内缓存，服务重启后丢失。
5. 还没有 Semantic Kernel 编排层，工具调用流程仍是固定代码路径。
6. 缺少安装包、启动器、配置向导和客户部署脚本。
7. 权限、租户、用户会话、数据脱敏仍是生产化前置项。

### P0：MVP 必须先做

1. 固定外部集成 API 契约和 Plugin Contract。
2. 完成 AI Gateway 的 `/demo`、`/openapi.json`、`/plugin-manifest.json`。
3. 完成 `TestDataFileAdapter`：先读 JSON fixture，再读 CSV。
4. 用 DuckDB / Pandas / Polars 做确定性统计，不让 LLM 直接算关键指标。
5. 完成 `get_test_run_summary` 和 `compare_test_runs`。
6. 完成 `FeishuCliProvider` 的搜索和正文读取闭环。
7. 完成一个带测试数据来源和飞书来源引用的回答闭环。
8. 支持模型 API、业务 API 和飞书 CLI 配置化。
9. 完成用户身份、ACL 和审计 ID 传递。
10. 完成 Host Context 和最小 Audit Log，让 Copilot 具备上下文感知和可追踪基础。

### P1：MVP 稳定后再做

1. Mock Host 或 JSON fixture 替换为真实客户业务 API、导出文件或 PDX Adapter。
2. 把 Host Context 和 Audit Log 从进程内缓存升级为可选持久化。
3. 把现有 summary / compare / knowledge / model config 包成 SK Plugin。
4. 接入 ydata-profiling，生成测试数据画像。
5. 接入 Great Expectations，沉淀确定性质量规则。
6. 接入 Evidently，做两批测试结果分布变化/漂移分析。
7. 接入 PyGWalker / Graphic Walker，做可视化探索。
8. 把 `IndexedRagProvider` 作为可选后端接入。
9. 增量同步、删除同步、Hybrid Search、Rerank。
10. 50 到 100 条评测集和 Token/延迟监控。

### P2：后续能力

1. PostgreSQL 元数据和同步任务。
2. Qdrant / PGVector。
3. Sheet、Base、PDF、PPT 和图片 OCR。
4. 多项目、多租户知识库。
5. 测试报告生成。
6. Human-in-the-loop 审批。
7. MCP / OpenAPI 工具接入。
8. JSON Schema 驱动动态 UI。
9. assistant-ui / AG-UI / CopilotKit Agent UI。

### P3：暂缓

1. 自动修改测试配置。
2. 自动启停测试设备。
3. LLM 直接生成并执行代码。
4. 完全自由的动态 UI。
5. 复杂多 Agent 自主协同。

备注：一句话生成 UI 不是不能做，而是不能第一版就让模型自由生成生产模块。更稳的路线是先让模型生成 JSON Schema / UI Schema，前端用成熟组件渲染，用户确认后再保存。

## 3. MVP 完成定义

MVP 不是“做出一个聊天窗口”，而是完成以下闭环：

```text
客户软件外部 API / Mock Host / 测试文件
  -> TestDataPlugin
  -> 结构化测试结果
  -> SK 编排
  -> 数据分析结论

飞书 CLI
  -> search
  -> fetch
  -> 标准化
  -> 带飞书引用回答
```

向量同步、Embedding 和 PostgreSQL 元数据迁移属于后续可选 Provider，不是 MVP 的完成前置条件。

## 4. 第一个开发任务

建议第一个任务命名为：

> `P0-001 Test Data File Analysis + Feishu CLI Spike`

输入：

- 一个客户软件测试数据 API 契约、Mock Host、JSON fixture 或脱敏 PDX 样例。
- 一个飞书知识库 Space。
- 一个 Wiki 节点。
- 一个用户身份。

输出：

- 一份结构化测试运行摘要。
- 一份两次测试对比结果。
- 一份符合 `contracts/document.schema.json` 的飞书标准文档 JSON。
- 一条带测试数据来源和飞书来源的回答。

这个任务完成后，再评估真实业务 API、PDX 解析工具、向量库和更深度的客户软件集成。

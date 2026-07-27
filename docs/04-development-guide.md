# 开发文档与验收标准

## 1. 开发准则

### 1.1 能用标准库，就不用自写实现

- 能用 Python / .NET 标准库解决的功能，优先使用标准库。
- 不为了简单 JSON、HTTP、CLI、哈希或文件操作引入额外依赖。
- 引入第三方包前，说明它解决了什么问题，以及标准库为什么不够。

### 1.2 已有成熟项目，优先复用

- 已有成熟开源项目时，优先通过 package、git dependency、git submodule 或独立服务复用。
- 不直接复制大段代码到项目里。
- 复用前确认许可证、版本、平台兼容性和安全状态。
- 用本项目自己的 Adapter / Wrapper 隔离第三方项目，避免业务代码直接绑死实现。
- 固定版本、Tag 或 commit，不依赖不可追踪的 latest。
- 数据分析优先复用 DuckDB、Pandas、Polars、Great Expectations、Evidently、ydata-profiling 等成熟项目。
- 动态 UI 优先复用 JSON Schema UI、assistant-ui、AG-UI、CopilotKit 等成熟项目或协议。

备注：复用开源不是“把一堆库塞进项目”。正确做法是先用最小依赖跑通一个业务闭环，库只藏在 Adapter 后面。

### 1.3 不重复造轮子

- 不自研已有的文档解析器、向量数据库、HTTP 客户端、CLI 解析框架或 Agent 编排框架。
- 如果现有项目不完全满足需求，先评估配置、扩展点或 Adapter，再考虑自研。
- 新抽象必须对应至少一个真实变化点；单次使用的逻辑优先保持简单。

### 1.4 先契约，后实现

- 没有客户源码时，先固定 HTTP/OpenAPI、CLI 或文件契约。
- 用 Mock Host 或 JSON fixture 验证 AI 逻辑，不猜测客户软件内部实现。
- 真实客户接口出现后，只替换 Adapter 和配置。

### 1.5 MVP 优先

- 先完成只读数据分析、飞书查询、模型 API 配置和审计。
- 不提前做动态 UI、多 Agent、全量 RAG 迁移或高风险写操作。
- 每个任务都要有可运行的验收路径。

## 2. 分支和提交

建议分支：

```text
main
develop
feature/*
bugfix/*
```

提交信息示例：

```text
feat(feishu): sync one docx node
feat(rag): add citation metadata
fix(acl): filter deleted document chunks
test(plugin): validate test run summary schema
docs: update phase one roadmap
```

## 3. API 契约

所有跨服务 API 需要：

- JSON Schema 或 OpenAPI。
- 明确错误码。
- `request_id`。
- `trace_id`。
- `user_id` 或等价身份。
- `project_id`。
- 超时和重试约定。

## 4. RAG 查询 API 草案

```http
POST /api/v1/knowledge/query
Content-Type: application/json
X-Request-Id: req_xxx
```

```json
{
  "query": "这个测试项的通过标准是什么？",
  "project_id": "geely-test",
  "top_k": 8,
  "include_citations": true
}
```

返回：

```json
{
  "request_id": "req_xxx",
  "answer": "......",
  "citations": [
    {
      "document_id": "doc_xxx",
      "title": "测试规范",
      "source_url": "https://example.feishu.cn/wiki/xxx",
      "section_path": [
        "第三章",
        "通过标准"
      ],
      "score": 0.91
    }
  ],
  "warnings": [],
  "usage": {
    "input_tokens": 1200,
    "output_tokens": 300
  }
}
```

## 5. Plugin 开发规范

每个 Plugin 函数必须注明：

```text
name
description
input_schema
output_schema
permission
risk_level
side_effect
requires_confirmation
timeout_ms
audit_level
```

Phase 1 只开放：

- 知识检索。
- 测试数据只读查询。
- 测试数据统计分析。
- 报告草稿生成。

Phase 1 禁止：

- 修改测试配置。
- 修改设备参数。
- 启停测试设备。
- 删除测试数据。
- 自动发起正式流程。

## 6. 测试策略

### 单元测试

- Token 解析。
- 文档标准化。
- Content Hash。
- Chunk 切分。
- ACL 过滤。
- Plugin 参数校验。
- 测试数据文件解析。

### 集成测试

- 飞书 Connector 与测试账号。
- Mock Host。
- 客户导出文件 fixture。
- AI Gateway 到 Plugin。

### RAG 评测

至少维护：

- 50 条标准问题。
- 每条问题对应期望来源。
- 召回率。
- 引用准确率。
- 答案完整性。
- 无依据拒答率。

## 7. 观测指标

| 指标 | 说明 |
| --- | --- |
| `rag_latency_ms` | RAG 总耗时 |
| `retrieval_latency_ms` | 检索耗时 |
| `llm_latency_ms` | 模型耗时 |
| `retrieval_hit_rate` | 是否命中期望文档 |
| `citation_accuracy` | 引用是否准确 |
| `tool_call_success_rate` | Plugin 调用成功率 |
| `token_usage` | 输入输出 Token |
| `sync_success_rate` | 飞书同步成功率 |
| `acl_rejection_count` | ACL 拒绝次数 |
| `test_file_parse_success_rate` | 测试数据文件解析成功率 |
| `test_file_parse_latency_ms` | 测试数据文件解析耗时 |

## 8. 第一批任务拆分

| 编号 | 任务 | 优先级 | 完成标准 |
| --- | --- | --- | --- |
| P0-001 | Feishu CLI Provider | P0 | 能搜索和读取有权限的飞书文档 |
| P0-002 | `TestDataFileAdapter` 契约 | Done | 能接收测试文件路径并输出标准模型，第三方解析库只能藏在 Adapter 后 |
| P0-003 | JSON fixture / CSV 解析 | Done | 不依赖真实 PDX 也能跑通分析；优先标准库，必要时接 DuckDB |
| P0-004 | `get_test_run_summary` | Done | 返回结构化测试摘要，关键指标由确定性代码计算 |
| P0-005 | `compare_test_runs` | Done | 返回两次测试的差异，后续可接 Evidently |
| P0-006 | 模型 API 配置 | Done | 不改代码即可切换 API |
| P0-007 | AI Gateway 查询接口 | Done | 返回回答、引用、request_id；错误响应统一为 request_id + error.code + error.message |
| P0-008 | MVP 评测和审计 | Done | `evals/run_eval.py` 覆盖 Copilot 页面、文件分析、对比、模型 fallback 和错误响应 |
| P0-009 | Host Context 接入契约 | Done | 宿主软件可通过 `/api/v1/host/context` 传入当前项目、Run 和文件路径 |
| P0-010 | 最小 Audit Log | Done | `/api/v1/audit/events` 可查看最近 API 调用、request_id、状态和错误码 |
| P0-011 | Tool Registry 契约 | Done | `/api/v1/tools` 暴露 Agent/SK 可消费的工具名、schema、风险和审计等级 |
| P0-012 | 宿主集成 Demo 包 | Done | `samples/host-integration` 可模拟宿主软件传入上下文、调用分析、对比结果和打开 Copilot |
| P0-013 | 产品展示前端 | Done | `/showcase` 展示宿主软件模拟台 + Copilot 右侧栏，并能调用分析、对比和 Host Context |
| P1-001 | PDX 工具链调研 | P1 | 找到官方工具、SDK 或样例格式 |
| P1-002 | PDX Adapter | P1 | 能解析脱敏 PDX 样例 |
| P1-003 | IndexedRagProvider | P1 | 向量检索作为可选后端 |
| P1-004 | 数据画像 | P1 | 接入 ydata-profiling 或同类工具生成可审计报告 |
| P1-005 | 数据质量规则 | P1 | 接入 Great Expectations 或同类工具校验阈值、缺失值、范围 |
| P1-006 | 可视化探索 | P1 | 接入 PyGWalker / Graphic Walker 或同类工具，不自研 BI |
| P2-001 | Schema 动态 UI | P2 | LLM 只生成 JSON Schema / UI Schema，前端成熟组件渲染 |

## 9. 开发完成标准

MVP 完成需要满足：

1. 可以通过飞书 CLI 搜索和读取一篇有权限文档。
2. 可以通过 JSON fixture、客户导出文件或 PDX Adapter 读取测试运行摘要。
3. 可以完成一次只读数据分析。
4. 模型 API、业务 API、飞书 CLI 和测试文件路径均可配置。
5. 不需要客户源码即可运行。
6. 请求、工具调用和输出可审计。
7. 有标准评测集和基础性能数据。

## 10. MVP 自检

AI Gateway 的最小产品自检：

```powershell
cd D:\geely-ai-platform\src\ai-gateway
$env:PYTHONPATH='src'
python evals\run_eval.py
```

当前覆盖：

- 产品展示页可访问。
- Copilot 页面可访问。
- Tool Registry 可读取。
- Host Context 可写入和读取。
- CSV 测试文件可分析。
- 两次测试结果可对比。
- 模型未配置时可 fallback。
- 最近 API 调用可进入 Audit Log。
- 坏 JSON 返回 `invalid_json`。
- 缺文件返回 `bad_request`。

后续接入 SK、真实飞书、PDX Adapter 或正式模型 API 前后，都应先跑这组自检。

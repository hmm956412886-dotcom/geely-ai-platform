# AI Gateway

这是第一版产品 MVP：基础 Gateway 保持无依赖 Python HTTP 服务，Semantic Kernel 作为可选工具编排层，客户软件始终通过稳定 REST API 集成。

## 接口

```text
GET  /health
GET  /demo
GET  /showcase
GET  /copilot
GET  /openapi.json
GET  /plugin-manifest.json
GET  /api/v1/tools
GET  /api/v1/model/config
GET  /api/v1/host/context
POST /api/v1/host/context
GET  /api/v1/audit/events
POST /api/v1/analyze
POST /api/v1/test-data/summary
POST /api/v1/test-data/compare
POST /api/v1/test-data/insights
POST /api/v1/knowledge/query
POST /api/v1/agent/query
```

## 本地运行

```powershell
cd D:\geely-ai-platform\src\ai-gateway
$env:PYTHONPATH='src'
python -m ai_gateway.server --port 8765
```

可选安装 DuckDB 数据分析引擎：

```powershell
python -m pip install -e .[analytics]
```

备注：不安装 DuckDB 也能运行，`/api/v1/test-data/insights` 会自动回退到标准库统计。安装 DuckDB 后，CSV 洞察会走 SQL 引擎，更适合后续大文件和多维分析。

启用 Semantic Kernel 模型工具编排：

```powershell
python -m pip install -e .[agent]
```

不安装该可选依赖或不配置模型时，`/api/v1/agent/query` 使用确定性只读工具选择器，Copilot 仍可离线演示。

打开产品展示页：

```text
http://127.0.0.1:8765/showcase
```

侧边栏 Copilot 面板：

```text
http://127.0.0.1:8765/copilot
```

网站或桌面软件嵌入：

```html
<iframe
  title="Geely AI Copilot"
  src="http://127.0.0.1:8765/copilot"
  style="width: 440px; height: 100vh; border: 0"
></iframe>
```

## MVP 自检

```powershell
cd D:\geely-ai-platform\src\ai-gateway
$env:PYTHONPATH='src'
python evals\run_eval.py
```

期望输出：

```text
PASS copilot_page
PASS showcase_page
PASS tools_registry
PASS analyze_csv
PASS host_context_roundtrip
PASS compare_runs
PASS insights_csv
PASS model_fallback
PASS audit_events
PASS invalid_json_error
PASS missing_file_error
11 passed, 0 failed
```

这组自检覆盖产品展示页、Copilot 页面、Host Context、CSV 分析、两次测试对比、数据洞察、模型 fallback、审计事件、坏 JSON 和缺文件错误响应。

## 宿主软件怎么接

优先顺序：

1. 宿主软件先调用 `POST /api/v1/host/context`，传入当前项目、Run 和测试文件路径。
2. 演示时打开 `/showcase`，真实嵌入时 WebView 或 iframe 打开 `/copilot`，作为宿主软件或公司网站的右侧 AI 面板。
3. 插件按钮调用 `POST /api/v1/analyze`，传入当前测试文件路径、`run_id` 或导出后的 JSON。
4. 数据面板或 Copilot 快捷按钮调用 `POST /api/v1/test-data/insights`，展示状态分布和 Top 失败原因。
5. 宿主软件读取 `/plugin-manifest.json`，按 manifest 自动注册 AI 面板和 API 操作。
6. 客户没有源码时，用外部启动脚本或桌面快捷方式启动 AI Gateway。

Host Context 示例：

```json
{
  "project_id": "GEELY_TEST",
  "run_id": "RUN_001",
  "source_file": "D:\\test-results\\run_001.csv",
  "target_file": "D:\\test-results\\run_000.csv",
  "current_view": "test_result_detail",
  "user_id": "tester"
}
```

备注：Host Context 当前是进程内缓存，服务重启后恢复默认演示上下文。

白话备注：我们现在做的是“AI 外挂小服务”。宿主软件只要能打开网页或发 HTTP 请求，就能先接上。

## Tool Registry

Agent / SK / 宿主插件生成器读取：

```text
GET /api/v1/tools
```

返回内容包含每个工具的：

```text
name
description
method
path
input_schema
output_schema
side_effect
requires_confirmation
risk_level
audit_level
```

备注：`/plugin-manifest.json` 更像“宿主软件怎么挂上 AI 面板和 API”的说明书；`/api/v1/tools` 更像“智能体可以调用哪些工具、参数是什么、风险多高”的说明书。后续接 Semantic Kernel 时，优先从这里生成 Plugin / Function Contract。

离线契约文件：

```text
contracts/tool-registry.json
```

## 审计事件

查询最近 API 调用：

```text
GET /api/v1/audit/events
```

当前审计是进程内最近 100 条事件，包含：

```text
timestamp
method
path
status
request_id
error_code
project_id
run_id
user_id
current_view
```

备注：这是 MVP 审计，不是生产日志系统。生产环境后续应接数据库、OpenTelemetry 或客户自己的审计平台。

## 当前实现

- 测试数据分析支持演示数据、JSON 文件和 CSV 文件。
- 飞书知识库返回演示引用。
- 所有操作都是只读。
- 不写入客户数据库。
- 不控制测试设备。

## 文件分析调用示例

```powershell
Invoke-RestMethod `
  -Method Post `
  -ContentType 'application/json' `
  -Uri 'http://127.0.0.1:8765/api/v1/analyze' `
  -Body '{"source_file":"D:\\geely-ai-platform\\src\\ai-gateway\\tests\\fixtures\\test-run-cases.csv"}'
```

JSON / CSV 最小字段：

```text
run_id,project_id,case_id,name,status,reason
```

`status` 支持 `passed`、`failed`、`warning` 等常见写法。通过率、失败数、失败用例由确定性代码计算，AI 只做解释。

数据洞察：

```powershell
Invoke-RestMethod `
  -Method Post `
  -ContentType 'application/json' `
  -Uri 'http://127.0.0.1:8765/api/v1/test-data/insights' `
  -Body '{"source_file":"D:\\geely-ai-platform\\src\\ai-gateway\\tests\\fixtures\\test-run-cases.csv"}'
```

返回内容包含：

```text
engine
total_cases
passed_cases
failed_cases
warning_cases
pass_rate
status_counts
failure_reasons
```

白话备注：`summary` 是“这次测试整体如何”，`compare` 是“这次和上次比怎样”，`insights` 是“从数据里直接抓分布和 Top 问题”。这三个都应先保持只读、可审计、可复现。

## 模型 API 配置

默认不调用外部模型，`/api/v1/agent/query` 使用本地确定性选择器。安装 `agent` 可选依赖并配置模型后，Semantic Kernel 会从 `/api/v1/tools` 选择只读 REST 工具：

```powershell
$env:AI_MODEL_BASE_URL='https://api.example.com/v1'
$env:AI_MODEL_API_KEY='客户自己的 Key'
$env:AI_MODEL_NAME='客户模型名'
$env:AI_MODEL_TIMEOUT_SECONDS='30'
```

检查配置状态：

```text
GET /api/v1/model/config
```

调用模型分析：

```powershell
Invoke-RestMethod `
  -Method Post `
  -ContentType 'application/json' `
  -Uri 'http://127.0.0.1:8765/api/v1/analyze' `
  -Body '{"source_file":"D:\\geely-ai-platform\\src\\ai-gateway\\tests\\fixtures\\test-run-cases.csv","use_model":true}'
```

备注：配置查询接口只返回是否已配置 Key，不返回 Key 本身。

## 错误响应

业务 API 失败时统一返回：

```json
{
  "request_id": "req_xxx",
  "error": {
    "code": "bad_request",
    "message": "source_file does not exist: ..."
  }
}
```

当前错误码：

```text
invalid_json
bad_request
not_found
```

宿主软件集成时优先记录 `request_id`，再把 `error.message` 展示给用户或写入日志。

两次测试对比：

```powershell
Invoke-RestMethod `
  -Method Post `
  -ContentType 'application/json' `
  -Uri 'http://127.0.0.1:8765/api/v1/test-data/compare' `
  -Body '{"baseline_file":"D:\\geely-ai-platform\\src\\ai-gateway\\tests\\fixtures\\test-run-cases.csv","target_file":"D:\\geely-ai-platform\\src\\ai-gateway\\tests\\fixtures\\test-run-cases-target.csv"}'
```

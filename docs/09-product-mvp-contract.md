# 产品 MVP 集成契约

## 1. 结论

当前最应该先做的是“可嵌入产品壳”，不是先优化底层能力。

交付形态建议固定为：

```text
AI Gateway 进程
+ WebView 面板
+ HTTP/OpenAPI
+ Plugin Manifest
+ 配置模板
+ 只读数据 Adapter
```

白话备注：这相当于把 AI 做成一个独立小产品。吉利测试软件只是第一个宿主，后续其他软件也能按同一套方式接入。

## 2. 给宿主软件暴露什么

### 2.1 WebView 面板

产品演示打开：

```text
http://127.0.0.1:8765/showcase
```

宿主软件真实嵌入打开：

```text
http://127.0.0.1:8765/copilot
```

`/showcase` 适合第一轮演示和客户评审，能同时看到宿主软件模拟台和右侧 AI 面板。`/copilot` 是真正可复用的侧边栏组件，适合嵌入客户软件 WebView 或公司网站 iframe。

当前还保留 `/demo` 作为简单演示页；正式嵌入优先使用 `/copilot`。

### 2.2 HTTP API

宿主软件或插件按钮调用：

```http
GET  /api/v1/host/context
POST /api/v1/host/context
GET  /api/v1/audit/events
GET  /api/v1/tools
POST /api/v1/analyze
POST /api/v1/test-data/summary
POST /api/v1/test-data/compare
POST /api/v1/knowledge/query
```

适合真实集成。按钮点击后，把当前测试任务、测试文件路径或导出数据传给 AI Gateway。

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

白话备注：Host Context 是让 Copilot “知道你当前在看哪次测试”的关键入口。没有它，Copilot 只是一个网页；有了它，才开始像智能体工作台。

### 2.3 Plugin Manifest

宿主软件读取：

```text
GET /plugin-manifest.json
```

它描述：

- AI 面板入口。
- 支持哪些 API。
- 每个 API 是否只读。
- 是否需要二次确认。

白话备注：manifest 就像“插件说明书”。宿主软件不需要知道 AI 内部怎么做，只要知道能调用哪些能力。

### 2.4 OpenAPI

开发联调读取：

```text
GET /openapi.json
```

正式项目里可以用 OpenAPI 生成 C#、Python、Java 或 TypeScript 客户端。

### 2.5 Tool Registry

Agent / SK / 宿主插件生成器读取：

```text
GET /api/v1/tools
```

它描述每个 AI 工具的：

- `name`：工具名，后续可映射为 SK Function 或 Agent Tool。
- `method` / `path`：真实 HTTP 调用入口。
- `input_schema` / `output_schema`：参数和返回结构。
- `side_effect`：是否只读，或是否会改本地状态。
- `requires_confirmation`：未来高风险动作是否需要用户确认。
- `risk_level` / `audit_level`：给宿主软件、安全审计和 Agent 决策使用。

白话备注：manifest 是“这个插件怎么挂到软件里”；Tool Registry 是“智能体能用哪些按钮、每个按钮怎么按、按了会不会有风险”。我们现在先把按钮说明书定好，后面接 Semantic Kernel 时就不需要重新定义一套工具协议。

离线文件：

```text
contracts/tool-registry.json
```

## 2.6 统一错误格式

所有业务 API 的错误响应都带 `request_id`：

```json
{
  "request_id": "req_xxx",
  "error": {
    "code": "bad_request",
    "message": "source_file does not exist: ..."
  }
}
```

宿主软件应该：

- 记录 `request_id`，方便排查。
- 根据 `error.code` 做程序判断。
- 把 `error.message` 作为用户可读提示。

当前错误码：

| code | 含义 |
| --- | --- |
| `invalid_json` | 请求体不是合法 JSON |
| `bad_request` | 参数错误、文件不存在、文件类型不支持 |
| `not_found` | 路由不存在 |

## 3. 客户侧最小改造

如果客户有源码：

- 加一个菜单或按钮：打开 AI 面板。
- 点击“分析当前测试”时，把 `run_id`、文件路径或导出 JSON 发给 AI Gateway。
- 展示 AI Gateway 返回的结论、引用和 `request_id`。

如果客户没有源码：

- 用外部启动脚本启动 AI Gateway。
- 让客户手动选择导出的测试文件。
- 或等客户提供 CLI / API / 插件机制后再自动传参。

## 4. API Key 怎么处理

模型 API 不写死在代码里，由客户部署时配置：

```text
AI_MODEL_BASE_URL
AI_MODEL_API_KEY
AI_MODEL_NAME
AI_MODEL_TIMEOUT_SECONDS
```

白话备注：卖给客户时，不是把我们的 Key 打包进去，而是让客户填自己的模型服务地址和 Key。这样数据、费用、权限都归客户自己控制。

当前 AI Gateway 提供只读配置检查：

```text
GET /api/v1/model/config
```

它只返回 `configured`、`base_url`、`model`、`api_key_configured`，不返回 API Key。

## 5. 第一版演示闭环

1. 启动 AI Gateway。
2. 打开 `/copilot`。
3. 输入“分析本次动力系统测试失败原因”。
4. Gateway 返回演示测试摘要、飞书引用和下一步建议。
5. 再把演示数据替换成真实测试文件 Adapter。

当前已经支持的文件输入：

```http
POST /api/v1/analyze
Content-Type: application/json
```

```json
{
  "source_file": "D:\\geely-ai-platform\\src\\ai-gateway\\tests\\fixtures\\test-run-cases.csv"
}
```

CSV 最小字段：

```text
run_id,project_id,case_id,name,status,reason
```

白话备注：客户软件未来只要把当前测试导出的文件路径传过来，AI Gateway 就能先算摘要，再给分析结论。

两次测试对比：

```http
POST /api/v1/test-data/compare
Content-Type: application/json
```

```json
{
  "baseline_file": "D:\\geely-ai-platform\\src\\ai-gateway\\tests\\fixtures\\test-run-cases.csv",
  "target_file": "D:\\geely-ai-platform\\src\\ai-gateway\\tests\\fixtures\\test-run-cases-target.csv"
}
```

返回内容包含：

- baseline run id。
- target run id。
- 总用例数差异。
- 通过用例数差异。
- 失败用例数差异。
- 通过率差异。

## 6. 后续替换点

| 当前 MVP | 后续真实实现 |
| --- | --- |
| 演示测试数据 | 已支持 JSON/CSV，后续接 Excel/PDX Adapter |
| 演示飞书引用 | lark-cli 搜索和正文读取 |
| 固定分析文本 | 已支持 OpenAI-compatible 模型 API 配置；后续接 Semantic Kernel |
| `/demo` 简单页面 | 正式 AI 面板 |
| 本地配置 | 客户环境变量或密钥管理 |

## 7. 不做什么

第一版不做写操作，不自动改测试配置，不控制设备，不直接连客户数据库。

原因很简单：先证明 AI 能看懂测试数据、能引用规范、能给出有依据的分析。写操作和自动控制等客户信任建立后再开。

## 8. MVP 自检

AI Gateway 提供本地自检脚本：

```powershell
cd D:\geely-ai-platform\src\ai-gateway
$env:PYTHONPATH='src'
python evals\run_eval.py
```

它会检查：

- `/copilot` 是否可访问。
- Host Context 是否可写入和读取。
- CSV 文件分析是否正常。
- 两次测试对比是否正常。
- 模型未配置时是否安全 fallback。
- 审计事件是否记录最近 API 调用。
- 错误响应是否包含 `request_id` 和稳定 `error.code`。

# MVP：无软件源码条件下的接入方案

## 1. 当前现实约束

目前拿不到客户测试软件源码，因此不采用 DLL 注入、内部类调用或源码级嵌入。

MVP 使用外置 AI Gateway：

```text
客户测试软件
  -> WebView / HTTP / CLI / 文件交换
  -> AI Gateway
  -> FeishuCliProvider + TestDataAdapter
  -> 客户可配置的模型 API
```

白话备注：先不要想着“把 AI 写进客户软件里”。先把 AI 做成旁边运行的服务，客户软件只负责打开它或把数据传给它。

## 2. 接入方式优先级

| 优先级 | 接入方式 | 适用情况 |
| --- | --- | --- |
| P0 | WebView 打开 AI 面板 | 客户软件能嵌入网页，最快展示 |
| P0 | HTTP / REST / OpenAPI | 客户软件能发请求或有插件按钮 |
| P0 | 文件导出 | 可导出 JSON、CSV、Excel、XML、PDX 或报告 |
| P1 | 客户提供 SDK / CLI | 有官方扩展能力但没有源码 |
| P1 | Mock Host | 客户接口没准备好，先并行开发 |
| P2 | 插件目录或脚本扩展 | 客户软件支持外部插件 |
| P3 | 源码级嵌入 | 未来客户开放源码或厂商支持深度集成 |

## 3. MVP 必须完成

1. AI Gateway 可以独立启动。
2. `/copilot` 可以嵌入宿主软件 WebView。
3. `/plugin-manifest.json` 描述集成入口。
4. `/openapi.json` 描述接口。
5. `/api/v1/analyze` 返回测试分析结论、数据依据、飞书引用和 `request_id`。
6. 模型 API Base URL、API Key、模型名通过配置提供。
7. 飞书知识库先走 CLI 查询，不做全量迁移。
8. 测试数据先走文件 Adapter 或 JSON fixture。

## 4. 明确不做

- 不修改客户软件源码。
- 不自动控制测试设备。
- 不修改测试配置。
- 不直接写客户数据库。
- 不做动态 UI。
- 不做多 Agent。
- 不做向量库全量迁移。

## 5. 推荐客户侧接口

如果客户软件能提供只读 API，第一阶段建议要这几个：

```http
GET /api/test-runs/{runId}/summary
GET /api/test-runs/{runId}/failures
GET /api/test-runs/compare?baseline={id}&target={id}
```

如果客户软件只能导出文件，则优先做 `TestDataAdapter`：

```text
测试软件导出文件
  -> TestDataAdapter
  -> 标准 TestRunSummary JSON
  -> AI Gateway 分析
```

白话备注：模型不要直接啃 PDX 大文件。先用确定性的解析器把数据整理成标准 JSON，再让模型解释。

## 6. 客户交付物

推荐交付：

- AI Gateway。
- WebView 入口 URL。
- OpenAPI 契约。
- Plugin Manifest。
- 配置模板。
- 启动脚本。
- 宿主集成样例：`samples/host-integration`。
- 飞书 CLI 登录/授权说明。
- 测试数据 Adapter 说明。
- AGENTS.md / 运维约束文档。

客户需要配置：

- 模型 API Base URL。
- 模型 API Key。
- 模型名称。
- 飞书 CLI 登录身份或应用凭据。
- 客户软件 API 地址或导出文件目录。

所有密钥只通过环境变量或客户自己的密钥管理系统提供，不写入 Git。

## 7. 验收标准

| 项目 | 验收标准 |
| --- | --- |
| 可展示 | 打开 `/copilot` 能看到 AI 面板并完成一次分析 |
| 可集成 | `/plugin-manifest.json` 能说明宿主软件如何接入 |
| 可调用 | `/api/v1/analyze` 能返回结构化结果 |
| 可配置 | 不改代码即可切换模型 API |
| 可追踪 | 每次响应包含 `request_id` |
| 可替换 | 演示数据可替换成真实文件 Adapter 或客户 API |
| 安全 | 第一版只读，不写配置，不控设备 |

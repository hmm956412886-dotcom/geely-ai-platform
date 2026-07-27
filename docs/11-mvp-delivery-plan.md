# MVP 交付计划

## 1. 原则

开发顺序固定为：

```text
计划和验收标准
  -> 契约或配置模板
  -> 最小代码实现
  -> 自动化验证
  -> 同步版本
```

白话备注：文档不是事后补说明，而是先把“下一步为什么做、做到什么程度算完成”写清楚。代码只能实现当前计划里的内容，不顺手扩功能。

## 2. 当前产品目标

当前阶段先把 Geely AI Platform 做成可交付的外置 AI Runtime：

```text
客户机器
  -> 启动 AI Gateway
  -> 配置客户自己的模型 API
  -> 宿主软件通过 WebView / HTTP / SDK 接入
  -> Copilot 只读分析测试数据
```

第一版交付重点不是安装包，也不是完整 Agent 平台，而是一个客户能启动、能配置、能验收的最小产品包。

## 3. P0-017：客户部署配置最小化

### 目标

让客户或内部演示人员不用改代码即可完成：

1. 配置网关地址、端口和模型 API。
2. 启动 AI Gateway。
3. 检查健康状态、模型配置状态和关键契约。
4. 打开 `/showcase` 或 `/copilot` 验证产品效果。

### 非目标

- 不做 Windows 安装程序。
- 不做 Docker 镜像。
- 不做系统服务注册。
- 不引入新依赖。
- 不改变模型 API 调用逻辑。
- 不把 API Key 写进 Git。

### 交付文件

| 文件 | 用途 |
| --- | --- |
| `config/runtime.env.example` | 客户部署环境变量模板，不含真实密钥 |
| `scripts/start-ai-gateway.ps1` | 启动 AI Gateway 的最小脚本 |
| `scripts/check-ai-gateway.ps1` | 验收健康状态、模型配置、工具契约和页面 |
| `docs/12-customer-deployment-guide.md` | 给客户或实施人员看的启动和验收步骤 |

### 验收标准

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-ai-gateway.ps1 -Port 8783
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-ai-gateway.ps1 -GatewayUrl http://127.0.0.1:8783
```

检查项：

- `/health` 返回 `ok`。
- `/api/v1/model/config` 不泄露 API Key。
- `/plugin-manifest.json` 可读取。
- `/api/v1/tools` 至少包含分析、洞察、对比工具。
- `/showcase` 和 `/copilot` 可访问。

## 4. 后续计划

| 编号 | 任务 | 触发条件 |
| --- | --- | --- |
| P0-018 | 开源 Copilot 插件底座 | Done：CopilotKit Spike 暴露强制 Runtime 耦合，最终采用 assistant-ui External Store Runtime |
| P0-019 | 前后端契约稳定化 | P0-018 跑通后，把前端 API 调用集中成 client |
| P0-020 | 演示交付包 | 前后端都能启动后，整理一键演示脚本 |
| P1-001 | PDX 工具链调研 | 拿到真实脱敏 PDX 样例或官方工具信息后 |
| P1-003 | Indexed RAG Provider | 飞书 CLI 查询不能满足性能或离线检索要求时 |
| P2-001 | Schema 动态 UI | P0 产品闭环稳定后再启动 |

# 客户部署指南

## 1. 交付物

第一版交付包包含：

```text
AI Gateway
Copilot WebView URL
OpenAPI / Plugin Manifest / Tool Registry
Host Connector 样例
运行配置模板
启动和检查脚本
```

白话备注：这不是最终安装包，而是能让客户机器先跑起来的最小产品包。先证明接入方式和数据分析闭环，再决定是否做安装器、服务化或 Docker。

## 2. 配置环境变量

复制模板：

```powershell
Copy-Item .\config\runtime.env.example .\.env
```

按客户环境修改 `.env`：

```text
AI_GATEWAY_HOST=127.0.0.1
AI_GATEWAY_PORT=8765
AI_MODEL_BASE_URL=https://api.example.com/v1
AI_MODEL_API_KEY=客户自己的 Key
AI_MODEL_NAME=客户模型名
AI_MODEL_TIMEOUT_SECONDS=30
```

注意：

- `.env` 已被 `.gitignore` 忽略。
- 不要把真实 API Key 写入 `runtime.env.example`。
- 不配置模型 API 时，系统仍可用本地确定性分析 fallback。

## 3. 启动 AI Gateway

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-ai-gateway.ps1 -EnvFile .\.env
```

指定端口：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-ai-gateway.ps1 -Port 8783
```

打开页面：

```text
http://127.0.0.1:8765/showcase
http://127.0.0.1:8765/copilot-shell/
```

Gateway 已直接提供生产构建的 Copilot 前端。需要独立联调前端时，另开 PowerShell：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-copilot-shell.ps1 -GatewayUrl http://127.0.0.1:8765
```

独立前端入口：

```text
http://127.0.0.1:5173/copilot-shell/
```

## 4. 检查部署状态

另开一个 PowerShell：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-ai-gateway.ps1 -GatewayUrl http://127.0.0.1:8765
```

同时检查独立前端：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-ai-gateway.ps1 `
  -GatewayUrl http://127.0.0.1:8765 `
  -CopilotUrl http://127.0.0.1:5173/copilot-shell
```

应看到：

```text
PASS /health
PASS /api/v1/model/config
PASS model config hides api_key
PASS /plugin-manifest.json
PASS tool analyze_test_run
PASS tool analyze_test_data_insights
PASS tool compare_test_runs
PASS /showcase
PASS Copilot shell URL
PASS Copilot shell JavaScript entry
```

## 5. 宿主软件接入

客户软件有 WebView：

```text
打开 /copilot-shell/?host_session_id=<宿主会话ID>&host_origin=<宿主网页Origin>
```

客户软件能发 HTTP：

```text
POST /api/v1/host/assets?host_session_id=<宿主会话ID>
POST /api/v1/host/context?host_session_id=<宿主会话ID>
POST /api/v1/analyze?host_session_id=<宿主会话ID>
POST /api/v1/test-data/insights
POST /api/v1/test-data/compare
```

网站 iframe 和桌面 WebView 的完整 `postMessage`、`asset_id` 示例见 `docs/10-reusable-copilot-embed.md`。

客户软件暂时没有源码：

```text
导出 CSV / JSON
运行 samples/host-integration
用外置 AI Gateway 完成只读分析
```

## 6. 当前安全边界

- 只读分析。
- 不写客户数据库。
- 不修改测试配置。
- 不控制测试设备。
- API Key 只在客户机器环境变量中配置。
- 响应中的 `request_id` 用于排查和审计。

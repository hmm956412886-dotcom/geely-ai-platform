# 客户部署指南

## 1. 交付物

第一版交付包包含：

```text
AI Gateway
Copilot WebView URL
OpenAPI / Plugin Manifest
Host Connector 样例
运行配置模板
启动和检查脚本
```

当前 CoreTest 可通过 `integrations/coretest/install.ps1` 安装真实右侧 Dock；网站和其他桌面软件继续复用同一 WebView URL 和 REST 契约。

## 2. 配置环境变量

复制模板：

```powershell
Copy-Item .\config\runtime.env.example .\.env
```

按客户环境修改 `.env`：

```text
AI_GATEWAY_HOST=127.0.0.1
AI_GATEWAY_PORT=8765
AI_GATEWAY_ACCESS_TOKEN=生成的高强度随机Token
AI_GATEWAY_HOST_TOKEN=另一个高强度随机Token
AI_MODEL_BASE_URL=https://api.example.com/v1
AI_MODEL_API_KEY=客户自己的 Key
AI_MODEL_NAME=客户模型名
AI_MODEL_TIMEOUT_SECONDS=30
AI_MODEL_WIRE_API=chat_completions
AI_MODEL_REASONING_EFFORT=
```

注意：

- `.env` 已被 `.gitignore` 忽略。
- 不要把真实 API Key 写入 `runtime.env.example`。
- 使用 OpenAI Responses API 的服务将 `AI_MODEL_WIRE_API` 设为 `responses`；可按模型能力设置 `AI_MODEL_REASONING_EFFORT=high`。仍必须在客户机器提供 `AI_MODEL_API_KEY`。
- 不配置模型 API 时，系统仍可用本地确定性分析；普通对话和测试代码生成需要真实模型配置。
- Gateway 只在当前机器使用时可以不设置 Token；绑定局域网地址或交付客户时必须同时设置访问 Token 和 Host Token，并通过 HTTPS / 反向代理暴露。
- `AI_GATEWAY_ACCESS_TOKEN` 交给 Copilot WebView，只能调用普通 API；`AI_GATEWAY_HOST_TOKEN` 只保留在可信桌面宿主/Sidecar，用于注册服务器本地文件，不能进入 WebView URL。
- 默认最多保留 256 个 Host Session、每个 Session 32 个 asset；可通过 `AI_GATEWAY_MAX_HOST_SESSIONS` 和 `AI_GATEWAY_MAX_ASSETS_PER_SESSION` 调整。宿主关闭窗口或任务时必须调用 `DELETE /api/v1/host/session`。
- 启用 Token 后不要从 WebView 传本地绝对路径；桌面宿主先调用 `/api/v1/host/assets` 注册文件，再把 `asset_id` 交给 Copilot。

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

启用访问 Token 时，检查脚本会自动读取当前进程的 `AI_GATEWAY_ACCESS_TOKEN`，也可显式传入 `-AccessToken`。

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
POST /api/v1/host/snapshot?host_session_id=<宿主会话ID>
POST /api/v1/copilot/query?host_session_id=<宿主会话ID>
POST /api/v1/analyze?host_session_id=<宿主会话ID>
POST /api/v1/test-data/insights
POST /api/v1/test-data/compare
```

CoreTest 的完整 Qt 集成见 `integrations/coretest`；通用 Python REST 客户端见 `samples/host-integration`。

客户软件暂时没有源码：

```text
导出 CSV / JSON
运行 samples/host-integration
用外置 AI Gateway 完成只读分析
```

## 6. 当前安全边界

- 汽车数据分析默认只读。
- 生成代码只在用户明确点击保存后写入当前项目 `generated_tests`，不自动执行。
- 不写客户数据库。
- 不修改测试配置。
- 不控制测试设备。
- API Key 只在客户机器环境变量中配置。
- 响应中的 `request_id` 用于排查和审计。

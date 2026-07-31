# 客户部署指南

## 1. 交付物

第一版目标交付包包含：

```text
HK CoreTest
右侧 AI Copilot
AI Gateway Sidecar
OpenCode Agent Sidecar
运行配置模板
```

注意：OpenCode 当前仍处于开发联调和第三方许可证审计阶段。`docs/14-open-source-compliance.md` 的
SBOM、Notices 和许可证门禁未通过前，构建脚本不得把 Agent Sidecar 加入正式客户 ZIP。

开发环境通过 `integrations/coretest/install.ps1` 将连接器安装到 CoreTest 源码。正式交付使用 `scripts/build-coretest-delivery.ps1` 生成包含 CoreTest、Qt WebEngine、Copilot 前端和 Gateway Sidecar 的完整 ZIP。

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

# OpenCode Runtime（开发阶段可使用 PATH 中的 opencode）
OPENCODE_COMMAND=opencode
OPENCODE_HOST=127.0.0.1
OPENCODE_PORT=4097
```

注意：

- `.env` 已被 `.gitignore` 忽略。
- 不要把真实 API Key 写入 `runtime.env.example`。
- 使用 OpenAI Responses API 的服务将 `AI_MODEL_WIRE_API` 设为 `responses`；可按模型能力设置 `AI_MODEL_REASONING_EFFORT=high`。仍必须在客户机器提供 `AI_MODEL_API_KEY`。
- Agent 模型必须支持可靠的工具调用；只支持普通文本补全的 OpenAI-compatible 服务不能完成文件和 Shell 工具循环。
- `OPENCODE_COMMAND` 可填写开发机 OpenCode 路径。正式客户版本必须匹配 `config/open-source-lock.json` 的锁定版本并校验 SHA-256，不得使用滚动最新版或来源不明的文件。
- OpenCode 只允许绑定 `127.0.0.1`。Runtime 密码由 Gateway 管理，不写入 WebView URL，也不作为普通环境配置分发。
- 不配置模型 API 时，系统仍可用本地确定性分析；普通对话和测试代码生成需要真实模型配置。
- Gateway 只在当前机器使用时可以不设置 Token；绑定局域网地址或交付客户时必须同时设置访问 Token 和 Host Token，并通过 HTTPS / 反向代理暴露。
- `AI_GATEWAY_ACCESS_TOKEN` 交给 Copilot WebView，只能调用普通 API；`AI_GATEWAY_HOST_TOKEN` 只保留在可信 CoreTest Connector 和 Sidecar，不能进入 WebView URL。
- 默认最多保留 256 个 Host Session；CoreTest 关闭窗口时必须释放当前会话。
- CoreTest Connector 只发送受限的文件内容或结构化 Snapshot，不向 WebView 暴露本地绝对路径。
- CoreTest Connector 使用 Host Token 注册当前工程根目录；Gateway 只向 WebView 返回“工作区已注册”，不返回实际路径。

## 3. 启动 AI Gateway

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-ai-gateway.ps1 -EnvFile .\.env
```

指定端口：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-ai-gateway.ps1 -Port 8783
```

只在开发联调时打开页面：

```text
http://127.0.0.1:8765/copilot-shell/
http://127.0.0.1:8765/plugin-manifest.json
http://127.0.0.1:8765/openapi.json
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
PASS Copilot shell URL
PASS Copilot shell JavaScript entry
```

## 5. CoreTest 接入

开发环境安装连接器：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\integrations\coretest\install.ps1 `
  -CoreTestRoot D:\path\to\hk-coretest-ai
```

随后按 CoreTest 自身方式启动应用。连接器负责：

- 启动或连接 Gateway Sidecar。
- 创建独立 `host_session_id` 并加载 Copilot WebView。
- 发布当前工程、选中文件和结构化汽车数据 Snapshot。
- 主窗口关闭时释放会话，并只终止由当前窗口启动的 Gateway。

Gateway REST/OpenAPI 仍是稳定集成协议，但第一版只以真实 CoreTest 完成验收。网站和其他宿主不在当前交付步骤中。

## 6. 当前安全边界

- 汽车数据分析默认只读。
- 生成代码只在用户明确点击保存后写入当前项目 `generated_tests`，不自动执行。
- 不写客户数据库。
- 不修改测试配置。
- 不控制测试设备。
- API Key 只在客户机器环境变量中配置。
- 响应中的 `request_id` 用于排查和审计。

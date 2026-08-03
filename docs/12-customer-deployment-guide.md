# 客户部署指南

## 1. 交付物

第一版目标交付包包含：

```text
HK CoreTest
右侧 CoreTest Agent
AI Gateway Sidecar
OpenCode Agent Sidecar
运行配置模板
```

OpenCode 使用 `config/open-source-lock.json` 锁定的官方 Windows x64 Runtime。构建脚本会校验 EXE 大小和 SHA-256，
并要求 MIT License、CycloneDX SBOM 和第三方 Notices 同时存在；任一项缺失或出现禁止许可证时停止打包。

开发环境通过 `integrations/coretest/install.ps1` 将连接器安装到 CoreTest 源码。正式交付使用 `scripts/build-coretest-delivery.ps1` 生成包含 CoreTest、Qt WebEngine、Copilot 前端和 Gateway Sidecar 的完整 ZIP。

## 2. 配置模型与部署参数

普通桌面部署优先在 CoreTest 右侧 Agent 底部点击“API”，填写 Base URL、API Key 和模型名。配置保存到
`%LOCALAPPDATA%\HK-CoreTest\ai-model.env`，API Key 不会回显；底部模型选择器用于在已配置模型之间切换。
已有项目旁 `ai-model.env/.env` 继续兼容；无人值守部署可用 `AI_MODEL_CONFIG_FILE` 指定固定路径。

无人值守部署或需要预置端口、鉴权 Token 时，再复制模板：

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

# OpenCode Runtime（正式包自动使用内置版本）
OPENCODE_COMMAND=auto
OPENCODE_HOST=127.0.0.1
OPENCODE_PORT=4097
```

注意：

- `.env` 已被 `.gitignore` 忽略。
- 不要把真实 API Key 写入 `runtime.env.example`。
- Agent 模型必须支持可靠的工具调用；只支持普通文本补全的 OpenAI-compatible 服务不能完成文件和 Shell 工具循环。
- 普通用户不需要配置 `OPENCODE_COMMAND`。开发机可以显式填写自有路径；正式客户版本只使用内置且通过 SHA-256 校验的锁定版本。
- OpenCode 只允许绑定 `127.0.0.1`。Runtime 密码由 Gateway 管理，不写入 WebView URL，也不作为普通环境配置分发。
- 不配置模型 API或未注册工作区时，AI 接口不可用并返回明确状态；测试数据摘要和比较等非 AI 接口仍可用。正式包不依赖系统安装 OpenCode。
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
- OpenCode 搜索和读取默认允许；原生 `edit/apply_patch` 修改和 Shell 命令逐次请求用户批准，直接 `write` 保持禁用以防绕过审批。
- 不写客户数据库。
- 不修改测试配置。
- 不控制测试设备。
- API Key 只在客户机器环境变量中配置。
- 响应中的 `request_id` 用于排查和审计。

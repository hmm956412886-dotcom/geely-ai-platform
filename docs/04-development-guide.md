# 开发与验收指南

## 原则

- 每项开发必须对应 `docs/13-reusable-ai-plugin-development-plan.md` 的可验收产品能力。
- 优先复用 CoreTest 服务、Python/Qt 标准能力和已固定的开源依赖。
- 不为单个实现增加接口、工厂、框架或未来配置。
- Gateway REST API 是宿主集成协议；宿主不能依赖 Gateway 内部 Python 模块。
- 所有汽车硬件和运行期数据工具默认只读。工作区 Agent 可以在审批后修改工程文件或执行命令，但不能调用 CAN 发送、UDS、刷写和设备控制能力。
- 文件和 SDK 使用优先交给 OpenCode 自行发现；只有 CoreTest 进程内状态才增加 Host Snapshot 或通用 CLI/MCP 桥。
- 客户源码、PDX、DBC、BLF、日志、数据库和密钥不得提交到本仓库。

## 目录职责

```text
frontend/copilot-shell/     可嵌入 Copilot UI
src/ai-gateway/             REST Gateway、OpenCode 生命周期/协议适配和确定性数据解析
integrations/coretest/      CoreTest Qt Host Connector 和安装集成
samples/host-integration/   与具体宿主无关的 REST SDK 样例
contracts/                  OpenAPI 和 Host Manifest
scripts/                    启动和部署检查
```

## 改动顺序

1. 在主计划中确认范围和验收标准。
2. 读取真实调用链和现有测试。
3. 为新增契约或错误先写最小测试。
4. 实现最少代码并运行相关测试。
5. 运行全量 Gateway、前端、Connector 和部署检查。
6. 检查 Git diff、CodeGraph、密钥和客户数据后再提交。

## Agent Runtime 要求

- OpenCode 始终作为独立 Sidecar 运行，绑定 `127.0.0.1`，不得嵌入 CoreTest 主进程。
- 工作区根目录只能由持有 Host Token 的 Connector 注册；普通 WebView 请求不得提交或读取绝对路径。
- 同一 Gateway 只绑定一个工作区根目录；不同工作区使用不同 Gateway 实例。
- Gateway 对外只返回工作区是否已注册、Runtime 版本和健康状态，不返回路径、密码和模型密钥。
- OpenCode 进程的 `cwd` 必须是已校验的工作区根目录。
- 测试不得依赖开发机已经安装 OpenCode；用伪进程和伪健康响应覆盖生命周期逻辑，真实二进制另做 Windows 集成验收。
- 所有 AI 回答只走 OpenCode；确定性代码只负责解析和传递事实，不生成替代回答。

## API 要求

- JSON 请求拒绝未知字段、无效类型和超限数据。
- 成功和失败均返回 `request_id`。
- 会话数据按 `host_session_id` 隔离并有数量/大小上限。
- 浏览器只持有 Access Token；本地文件注册和 Host Snapshot 写入使用 Host Token。
- OpenAPI 和 Plugin Manifest 是 Gateway 的唯一公开契约，并由运行时直接提供。
- OpenCode OpenAPI 是 Gateway 内部 Runtime 协议，不直接成为 CoreTest 宿主协议。

## 验证命令

完整命令以主计划“固定验证”为准。桌面集成额外执行：

```powershell
cd D:\geely-ai-platform
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-ai-gateway.ps1
git status --short
git diff --check
```

涉及 Qt UI、WebView 或打包的改动必须实际启动 CoreTest 并截图检查。纯单元测试不能替代桌面验收。

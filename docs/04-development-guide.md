# 开发与验收指南

## 原则

- 每项开发必须对应 `docs/13-reusable-ai-plugin-development-plan.md` 的可验收产品能力。
- 优先复用 CoreTest 服务、Python/Qt 标准能力和已固定的开源依赖。
- 不为单个实现增加接口、工厂、框架或未来配置。
- Gateway REST API 是宿主集成协议；宿主不能依赖 Gateway 内部 Python 模块。
- 所有汽车硬件和运行期数据工具默认只读。CoreTest 与 CoreTest Agent 产品源码永久只读；工作区 Agent 可在当前用户工程内自动修改文件、编写脚本和执行命令，但不能调用 CAN 发送、UDS、刷写和设备控制能力。
- 文件和 SDK 使用优先交给 OpenCode 自行发现；只有 CoreTest 进程内状态才增加 Host Snapshot 或通用 CLI/MCP 桥。
- 客户源码、PDX、DBC、BLF、日志、数据库和密钥不得提交到本仓库。

## 目录职责

```text
frontend/copilot-shell/     旧版 assistant-ui 回退界面
frontend/opencode-coretest/ 锁定版 OpenCode Web UI 的 CoreTest Profile 与构建产物
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
- OpenCode 进程的 `cwd` 必须是可信 Connector 注册的当前用户工程。明显的 CoreTest 或 CoreTest Agent 源码仓库根目录必须拒绝注册。
- 用户工程内的搜索、读取、编辑、写入和 Shell 自动允许，不逐步审批；OpenCode 文件/Web 工具拒绝外部目录和 Web 访问，硬件能力不注册。Shell 的操作系统边界还必须由客户安装目录 ACL 和网络策略验收。
- OpenCode 原生 `reasoning`、step、tool、todo、retry 和 patch 事件必须保留类型并分层呈现；最终回答使用 Markdown/GFM，不得把所有 part 拼成一段普通文本。
- CoreTest Dock 默认 440px，允许边缘拖拽，并提供 840px 展开/恢复；窄栏使用 OpenCode 原生底部“会话/变更”Tab，宽栏使用原生 Review 面板，禁止重复实现文件变更 UI。
- 输入框普通、简化和 Shell 提示必须使用 CoreTest 中文文案；Markdown 宽表格必须保留可见的横向滚动能力。
- CoreTest 进程内只读能力统一通过 `coretest-host` 暴露；Connector 使用随机 loopback 端口和随机令牌，Gateway 不得把地址、令牌或绝对路径返回 WebView。
- `coretest-host` 只允许显式登记的查询能力；禁止动态导入 `app.service` 方法，禁止注册 CAN、UDS、刷写和设备控制入口。
- Provider、模型和凭据优先使用 OpenCode 原生 Config/Auth API；不得再建设第二套多 Provider 数据库。
- OpenCode 使用 CoreTest 专属持久化目录；Gateway 只代理模型管理所需的受限接口，并强制保留工作区权限策略。
- 测试不得依赖开发机已经安装 OpenCode；用伪进程和伪健康响应覆盖生命周期逻辑，真实二进制另做 Windows 集成验收。
- 所有 AI 回答只走 OpenCode；确定性代码只负责解析和传递事实，不生成替代回答。
- 修改 OpenCode UI Profile、源码归档或构建脚本后，必须重新生成 UI SBOM、第三方 Notices 和全部静态资源哈希；零组件、未知许可证或资产计数不一致都必须阻断交付。

## API 要求

- JSON 请求拒绝未知字段、无效类型和超限数据。
- 成功和失败均返回 `request_id`。
- 会话数据按 `host_session_id` 隔离并有数量/大小上限。
- 浏览器只持有 Access Token；本地文件注册和 Host Snapshot 写入使用 Host Token。
- OpenAPI 和 Plugin Manifest 是 Gateway 的唯一公开契约，并由运行时直接提供。
- OpenCode OpenAPI 是 Gateway 内部 Runtime 协议，不直接成为 CoreTest 宿主协议。
- Provider API 的公开响应不得包含 API Key、OpenCode Runtime 密码、配置文件路径或工作区绝对路径。

## 验证命令

完整命令以主计划“固定验证”为准。桌面集成额外执行：

```powershell
cd D:\geely-ai-platform
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-ai-gateway.ps1
git status --short
git diff --check
```

涉及 Qt UI、WebView 或打包的改动必须运行 `integrations/coretest/smoke_test.py`。该脚本直接创建真实
`MainWindow`、激活测试工程，并从 Qt、Gateway 和 OpenCode 后端断言 Dock、SPA 路由、工作区、Host Context、
Snapshot 和 Runtime 状态；设置 `CORETEST_SMOKE_PROMPT` 后还会调用真实模型，设置
`CORETEST_SMOKE_REQUIRE_TOOL=1` 时要求至少一个 OpenCode 工具调用完成。功能通过与否不得依赖截图识别。

```powershell
cd D:\geely-ai-platform
$env:CORETEST_PROJECT_ROOT='D:\geely-ai-platform\customer-data\hk-coretest-ai\test\project\test'
python .\integrations\coretest\smoke_test.py

$env:CORETEST_SMOKE_PROMPT='调用 coretest-host 检查当前工程并分析 dbc_files/test.dbc'
$env:CORETEST_SMOKE_REQUIRE_TOOL='1'
python .\integrations\coretest\smoke_test.py
```

截图只用于人工检查布局、重叠、中文文案和品牌泄漏；需要时显式设置 `CORETEST_SMOKE_SCREENSHOT`，不能用截图代替
会话完成、工具调用、权限边界和最终结果断言。

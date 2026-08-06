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
正式 ZIP 验收可设置 `CORETEST_SMOKE_PROJECT_ROOT` 跳过工程选择窗口；该目录必须已经存在并包含 `config.db`，
否则 CoreTest 直接失败且不会创建目录。未设置时客户原有工程选择流程保持不变。

```powershell
cd D:\geely-ai-platform
$env:CORETEST_PROJECT_ROOT='D:\geely-ai-platform\customer-data\hk-coretest-ai\test\project\test'
python .\integrations\coretest\smoke_test.py

$env:CORETEST_SMOKE_PROMPT='调用 coretest-host 检查当前工程并分析 dbc_files/test.dbc'
$env:CORETEST_SMOKE_REQUIRE_TOOL='1'
python .\integrations\coretest\smoke_test.py
```

需要验证具体闭环时继续设置：

```powershell
$env:CORETEST_SMOKE_EXPECT_TOOLS='bash,read'
$env:CORETEST_SMOKE_EXPECT_DBC='test.dbc'
$env:CORETEST_SMOKE_TEST_PROVIDER='coretest'
$env:CORETEST_SMOKE_TEST_MODEL='gpt-5.5'
$env:CORETEST_SMOKE_EXPECT_FILE='generated_tests/test_agent_acceptance.py'
$env:CORETEST_SMOKE_EXPECT_TEXT='CORETEST_AGENT_ACCEPTANCE = True'
$env:CORETEST_SMOKE_FORBID_ANSWER_TEXT='OUTSIDE_SENTINEL_VALUE'
$env:CORETEST_SMOKE_REPORT='D:\temp\coretest-agent-acceptance.json'
```

截图只用于人工检查布局、重叠、中文文案和品牌泄漏；需要时显式设置 `CORETEST_SMOKE_SCREENSHOT`，不能用截图代替
会话完成、工具调用、权限边界和最终结果断言。

## 测试方法论与踩坑记录

验收按以下顺序取证，前一层不能被后一层替代：

1. 单元和协议测试验证输入、权限、状态机、超时与密钥隐藏。
2. `integrations/coretest/smoke_test.py` 在真实 `MainWindow`、`QDockWidget` 和 WebView 中验证宿主集成，并通过 Gateway/OpenCode API 验证工作区、Runtime、会话和工具结果。
3. 真实模型测试必须使用隔离的用户工程，设置 `CORETEST_SMOKE_REQUIRE_TOOL=1`，同时检查 Agent 最终回答、已完成工具调用和磁盘产物；只返回一段文本不算工作区 Agent 验收通过。
4. 截图只检查视觉效果，不能证明模型调用、工具执行、工作区边界或进程清理正确。
5. UI Profile 修改后必须依次执行：源码构建、合规材料生成、`install.ps1` 同步、源/目标静态文件逐项哈希比较、真实 CoreTest smoke。不得直接修改 `dist` 或只在独立浏览器页面验收。
6. CoreTest 只注册一个可信工程：Profile 隐藏添加、编辑、关闭和切换工程入口，但必须保留 OpenCode 原生新建会话入口；不要用宽泛的图标或 `aria-label` CSS 选择器误伤会话按钮。

遇到测试失败时，先记录失败方法和原因，再换方法；不得在后续会话重复使用已知无效方法：

| 无效或不充分的方法 | 原因 | 正确替代方法 |
| --- | --- | --- |
| 用浏览器插件打开本机 Agent 页面 | 客户端可能拦截 localhost，且不能证明页面运行在 CoreTest 内 | 使用 Qt/WebView smoke 创建真实 CoreTest `MainWindow` |
| 只靠截图判断功能通过 | 看不到 Gateway、工作区、模型、工具和清理状态 | 以 Qt 状态、DOM、Gateway API、OpenCode activity 和磁盘结果为主，截图为辅 |
| 在工程会话页断言首页“当前工程”标题 | 进入工程后 OpenCode 只渲染会话页，首页标题不在当前 DOM，导致假失败 | 查询实际可见的新建会话和工程管理控件，并触发新建会话后断言 `/new-session` |
| 让 Qt WebEngine 直接把 JavaScript 对象转换为 Python `dict` | 当前 Qt WebEngine 返回空字符串，无法区分脚本异常和空结果 | JavaScript 使用 `JSON.stringify` 返回结果或异常，Python 再用 `json.loads` 解析 |
| 在未发送消息的 `/new-session` 草稿页断言会话标题 | OpenCode 草稿还没有后端 Session，页面按设计不渲染标题 | 构建时校验 `session-title.ts` 补丁锚点；真实模型创建 Session 后再人工或端到端检查标题 |
| `document.querySelector(...).click()` 点击加号 | OpenCode 同时存在隐藏和可见输入器；Kobalte 菜单监听 pointer 事件 | 按可见尺寸选择元素，并发送 `pointerdown`、`pointerup`、`click` |
| 复用已经运行的 8765 Gateway | 旧进程可能持有另一组 Bearer Token，产生假鉴权失败 | 测试前检查监听进程；确认是临时开发 Gateway 后关闭，让 smoke 自主管理生命周期 |
| 只修改语言探测的默认回退值 | OpenCode 会从持久化语言设置恢复英文 | 同时迁移持久化 locale，并覆盖实际使用的 i18n key |
| 在 JSX 普通属性中写 `\uXXXX` | JSX 会把它显示为字面转义文本 | 使用 `prop={"\uXXXX"}` 或现有 i18n 字典 |
| 新终端直接运行 pnpm 或 Connector 测试 | 开发机没有全局 Node/pnpm，Python 也不会自动找到 Connector 包 | 每个终端显式设置锁定 Node/pnpm 路径和对应 `PYTHONPATH` |
| 用 Codex 通用 Python 运行 CoreTest Connector 全套测试 | 通用解释器不包含 CoreTest 使用的 `PySide6`，测试会在导入 Qt 模块时失败 | 使用 `Get-Command python -All` 定位已安装 `PySide6` 的 CoreTest/Python 解释器，再设置 `PYTHONPATH=.` 运行 Connector 测试 |
| headless smoke 激活工程后不扫描文件 | 与真实 `app.__main__` 启动顺序不同，导致 DBC/Trace 服务缓存为空，产生假桥接失败 | 创建 `MainWindow` 后调用 `project_file_service.scan_files()`，并用 `CORETEST_SMOKE_EXPECT_DBC` 断言已解析缓存 |
| 只设置 `CORETEST_SMOKE_TEST_PROVIDER` 时仍创建临时 OpenCode 状态目录 | Provider 配置存放在真实 CoreTest 状态目录，临时目录会让已配置 Provider 看起来不存在 | 只有 Prompt 和 Provider 测试都未启用时才隔离状态；真实 Provider 测试沿用本机 CoreTest 状态目录 |
| 在受限沙箱内运行完整交付构建 | `pnpm install --frozen-lockfile` 访问锁定依赖时会被系统以 `EACCES` 拒绝，重试不会改变结果 | 保留同一锁文件、Node 和 pnpm 参数，在获准联网的构建环境重跑；不得改用未锁定依赖或跳过 UI/合规重建 |
| 给 `build-coretest-delivery.ps1` 只留 120 秒外层超时 | 外层进程被终止后 PyInstaller 子进程仍可能继续生成 CoreTest ZIP，但不会执行最后的 Gateway 追加步骤，留下可打开却缺少 `ai-gateway/` 的半成品 | 使用至少 10 分钟超时并等待脚本成功返回；随后直接检查 ZIP 必须包含 `ai-gateway/geely-ai-gateway.exe`、内置 `opencode.exe`、864 个 UI 条目和当前中文 UI 文案 |
| 只启动客户 ZIP 到工程管理页就判断 Agent 可用 | Agent 工作区来自用户选择的工程，主窗口尚未创建时 Gateway 按设计不会启动 | 必须激活一个隔离工程并进入主窗口，再断言 Gateway、OpenCode、工作区、工具调用和退出清理 |
| 用通用 Windows 自动化反复点击 Qt `setIndexWidget` 内的按钮 | 该按钮可能不进入 UI Automation 控件树；固定坐标即使来自单元格边界，也可能因前台窗口和 DPI 不触发 | 最多复验一次聚焦后的点击；仍无 Qt 事件就停止，改为人工激活工程或以后增加正式的测试入口，不用截图冒充功能断言 |
| 按 `computer-use` 技能调用 `sky.documentation()` | 本机安装的 `@oai/sky` 未暴露该文档接口，且 `list_windows()` 返回 `EnumWindows 0x80070003` | 记录插件版本差异；本轮使用 Windows 原生 UI Automation 做只读控件检查，插件恢复前不重复该路径 |
| 用 `python -m unittest test.coretest_copilot...` 运行完整 CoreTest 仓库测试 | 客户仓库的 `test/` 目录不是 Python 包，模块路径导入会失败 | 使用 `python -m unittest discover -s test\coretest_copilot -p "test_*.py"`，并显式设置 `PYTHONPATH=.` |
| CoreTest 运行时直接对 `config.db` 执行 `Get-FileHash` | SQLite 文件被活动进程锁定，PowerShell 无法读取，不能据此判断 Agent 是否改库 | 在启动前和完全退出后比较数据库哈希；运行中只检查任务允许的文件变化和新增文件 |
| 用 UIA `SetValue`、`SendKeys` 或逐字符 `SendInput` 自动输入 WebView 中文 Prompt | OpenCode 的 contenteditable 输入器会丢失、重复或改写字符，UIA 按钮也不一定支持 `InvokePattern`；PowerShell 非终止错误还可能保留 0 退出码 | 正式 ZIP 的中文 Prompt 由人工输入并发送；自动验收继续从 Gateway/OpenCode activity、工程产物和退出状态取证，不能把乱码任务当成功 |
| Provider 在已完成部分工具步骤后失败时自动重发整轮 Prompt | 自动重放可能重复写文件、运行命令或调用 SDK，产生二次副作用 | 保留 OpenCode 的失败终态，错误卡片中文化；用户点击“恢复任务到输入框”后检查任务并手动重新发送，不在 Gateway 增加第二套自动重试循环 |

真实模型验收工程必须是明确的测试工程，不得使用 CoreTest、Gateway、Agent UI 或集成源码目录。测试前后记录文件清单和 Git 状态；只允许验收任务声明的工程文件变化。失败、超时和主动停止后必须确认 8765 无残留监听，异常 OpenCode session 已 abort 并释放。

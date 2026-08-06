# CoreTest 工作区智能体产品开发计划

## 0. 新会话接手基线（2026-08-06）

### 最终目标

在真实 HK CoreTest 主窗口右侧交付 `CoreTest Agent`。它不是带固定问答接口的聊天框，而是一个以当前
用户工程为唯一工作区、体验接近 Codex/Claude Code 的本地工作区智能体：第一次进入工程也能自行阅读目录、
理解架构、分析文件、发现并使用项目已有 SDK/CLI、生成或修改用户工程文件、运行命令和测试，并根据结果继续工作。

客户侧的完成体验必须是：启动一次 CoreTest，右侧 Agent 已随软件运行；客户只配置模型 API，不安装 Node、pnpm
或 OpenCode，不启动额外终端，也不手动维护 Gateway/Runtime。Agent 可以自动操作用户工程，但不能修改 CoreTest、
CoreTest Agent、Gateway、OpenCode 集成和 UI 等产品源码，也不能调用 CAN、UDS、刷写或设备控制能力。

### 已固定的产品方案

- 默认入口是 `/agent-native/`，直接使用锁定版 OpenCode 官方 Web UI 源码构建的 CoreTest Profile。
- `/copilot-shell/` 只作为旧 assistant-ui 回退，不再继续扩展为第二套 Agent UI 或状态机。
- OpenCode `serve` 是本地 Agent Sidecar。Gateway 按需启动一次，同一工程复用，退出 CoreTest 时统一关闭；客户不会看到额外窗口。
- Gateway 只负责可信工作区、生命周期、鉴权代理、路由白名单、路径/密钥保护和 `coretest-host` 只读桥；Agent loop、会话、工具、Diff 和模型交互由 OpenCode 负责。
- OpenCode 锁定为 `v1.18.10`，Commit `7902e04c3a67f7c69726bc955efb46e29214c797`，许可证为 MIT。
- 当前开发分支是 `solution-2-opencode`。不得把方案 1 的逐步审批和 assistant-ui 主界面重新带回方案 2。

### 当前实际进度

- OpenCode Runtime 的内置、按需启动、健康检查、复用、停止和故障隔离已经接通。
- 可信用户工程注册、产品源码工作区拒绝、浏览器路径隐藏、Runtime 密码注入和原生 API 白名单已经接通。
- OpenCode UI 源码已归档并校验；官方 UI 已从源码成功构建，Gateway 优先提供 `frontend/opencode-coretest/dist`。
- CoreTest Profile 已移除服务器/项目切换、PTY、分享等不开放入口；名称统一为 `CoreTest Agent`，底部保留模型切换、历史会话和“配置模型 API”。
- CoreTest Profile 只展示宿主已注册的当前工程，隐藏添加、编辑、关闭和切换工程入口；同一工程下保留 OpenCode 原生的新建会话与历史会话。曾因 CSS 误隐藏原生新建会话按钮，现已恢复并加入 Profile 回归测试。
- 侧栏默认宽度为 440px，保留 Qt 边缘拖拽调宽，并可从标题栏一键展开到 840px 或恢复；Markdown 宽表格保留横向滚动，不压缩列内容。
- 输入框的普通、简化和 Shell 状态均使用 CoreTest 中文提示；API 配置弹窗和 OpenAI-compatible 表单可以打开，浏览器控制台无错误。
- 原生 UI 启动需要的 `GET /path` 和 `GET /experimental/resource` 已代理，返回值仍由 Gateway 强制绑定到可信工作区。
- `coretest-host` 已提供工程、文件、DBC、Trace 和诊断的通用只读能力；硬件控制能力未注册。
- UI 依赖锁、CycloneDX 1.6 SBOM、第三方 Notices 和静态资源哈希已经生成。当前记录为 99 个生产依赖组件、864 个静态文件，阻断许可证为 0。
- 最近一次验证结果：Gateway 105 项、CoreTest Connector 38 项、示例宿主 4 项测试通过，Gateway eval 16 项通过、0 失败。真实 CoreTest smoke 已验证工作区注册、Host Context、Snapshot、OpenCode Runtime、中文原生菜单和 DBC 解析缓存（42 个报文）；截图不再作为功能通过条件。
- 现有 `coretest/gpt-5.5` 配置已通过真实 Provider 连接测试；同一真实 CoreTest 会话内完成 `coretest-host project.summary` 工具调用，退出后 Gateway/OpenCode 无残留。Provider-only smoke 的状态目录偏差已修复并实测通过。
- 隔离工程内已完成两次真实 Agent 写文件、运行 unittest 和结果回读闭环；工作区外哨兵读取/修改被拒绝且哈希未变化，允许的 Host CLI 能力精确锁定为 7 个只读查询。
- 正式 `HK-CoreTest_v2.0.0.zip` 已重复构建成功，包含 CoreTest、Gateway、锁定版 OpenCode Runtime、源码构建 UI、SBOM、Notices 和环境变量示例；本机解压后已用当前版本新建工程进入真实主窗口，包内 Gateway/OpenCode 自动启动且本轮 CoreTest 日志无错误，正常关闭后进程和端口全部释放。包内中文 Prompt 仍需人工完成一次工具闭环；干净 Windows、升级和 ACL 尚未验收。
- CoreTest 启动入口支持仅供验收使用的 `CORETEST_SMOKE_PROJECT_ROOT`；它只接受已存在且含 `config.db` 的工程，未设置时仍显示原工程管理窗口，用于让正式 ZIP 的主窗口验收不依赖不稳定的 GUI 点击。
- OpenCode 上游 SolidJS 补丁已进入锁文件和正式 UI 构建；Gateway 已支持 `/server/<server>/session/<id>` SPA 路由。打包构建强制把已校验 Runtime 固定为包内 `ai_gateway/bin/opencode.exe`，打包模式忽略外部 `OPENCODE_COMMAND` 并禁止运行时下载。
- 真实 CoreTest 会话已复现 Provider 在首次 `coretest-host` 工具调用后返回临时不可用：Host、Gateway、Runtime 和工作区均正常，失败来自模型上游。CoreTest Profile 现已把常见 502/503/504、限流、超时和鉴权错误转换为中文，并在错误卡片提供“恢复任务到输入框”；该入口复用 OpenCode 原生 revert，只恢复原任务，不自动重放可能已经产生副作用的工具步骤。修复后的正式 ZIP 仍需人工重发同一只读 Prompt 完成闭环。
- 上述修复已重新构建为正式 `HK-CoreTest_v2.0.0.zip`（363,987,600 字节，SHA-256 `D186E9B0B3D5CB0C1943765609BA8FDACFB76811D5EE68B4436C98E3578A3B84`）。ZIP 结构已核验为 4,646 个条目，包含 904 个 Gateway 条目、1 个锁定 OpenCode Runtime 和 864 个 UI 条目；从该 ZIP 解压启动的真实 CoreTest 已激活隔离工程并加载 `test.dbc`，Gateway health 为 `ok`。
- 当前工程/会话入口回归已通过真实 CoreTest smoke：三个工程管理入口不可见，OpenCode 原生“新建会话”按钮可见并能进入 `/new-session`，输入框菜单在新会话中仍可用。本轮源码 UI 重建后仍为 864 个静态文件，源/完整 CoreTest 目标哈希逐项一致；Gateway 106 项、Connector 38 项和示例宿主 4 项测试通过。

### 下一会话按此顺序继续

1. 使用第二套真实客户凭据验证多 Provider 新增、保存、删除、切换和连接测试；当前已有单元测试覆盖错误 Base URL、重复模型、密钥保留/隐藏和不支持 Provider，不能用伪造凭据冒充多 Provider 实测。
2. 使用修复后的正式 ZIP 人工重发 `coretest-host capabilities`、`project.summary` 和 `dbc.inspect` 只读 Prompt，确认 Provider 恢复时完成三个工具调用；再继续验证 OpenCode 原生 `question`、retry、compact、fork、Diff Review、撤销、异常断流、停止和恢复，不在 Gateway 或前端重写第二套循环。
3. 在解压后的正式客户 ZIP 中人工激活隔离工程，完成主窗口右侧 Agent、Provider、工具调用、工程写入、测试和退出清理闭环。只启动到工程管理页不算通过。
4. 在干净 Windows 环境验证完整客户 ZIP 的离线启动、首次 API 配置、升级、安装目录 ACL 和 CoreTest 既有硬件驱动的 VC80/90/120 运行库前置条件。
5. 由客户或法务完成第三方许可证最终审批；申请 MR 前整理双仓提交范围，且继续排除 `test/project/test/config.db` 和 `generated_tests/`。
6. 在上述外部验收完成前，不宣称“完整无错误”或“最终可交付”。

### 新会话必须注意

- 当前工作区有大量本阶段未提交修改和新增文件。先执行 `git status --short --branch`，不得 `reset --hard`、`checkout --` 或覆盖既有修改。
- 当前 `D:\geely-ai-platform` 的 Git remote 是 GitHub AI 开发仓库，分支为 `solution-2-opencode`；完整 CoreTest 的极狐仓库目标是 `https://jihulab.com/hk-group/hk-coretest-ai`。申请 MR 前必须确认自己位于正确仓库，不能把“已推 GitHub”当成“已更新极狐完整仓库”。
- 开发机不能假设全局存在 Node/pnpm。每个新 PowerShell 终端都要重新声明以下路径并把 Node 目录加入本终端 `PATH`：

```powershell
$node='C:\Users\humin\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
$pnpm='C:\Users\humin\.cache\codex-runtimes\codex-primary-runtime\dependencies\bin\fallback\pnpm.cmd'
$env:Path=(Split-Path -Parent $node) + [IO.Path]::PathSeparator + $env:Path

& $node --version  # 已验证 v24.14.0
& $pnpm --version  # 已验证 11.9.0
```

- OpenCode UI 构建和合规生成必须显式传入上述路径：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\build-opencode-ui.ps1 -Node $node -Pnpm $pnpm

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\generate-opencode-ui-compliance.ps1 -Node $node -Pnpm $pnpm
```

- `http://127.0.0.1:8768/agent-native/?host_session_id=visualtest` 是上一轮临时开发验收实例，不能假设新会话仍在运行。正式默认入口仍是 CoreTest 内嵌页面；独立开发启动默认使用 `8765`。
- 正式包必须携带锁定并校验过的 OpenCode Runtime 和源码构建 UI；不能要求客户联网下载依赖，也不能把开发机上的全局 `opencode.exe`、Node 或 pnpm 当作客户前置条件。

## 1. 产品定义

本项目交付的是嵌入 HK CoreTest 右侧的本地工作区智能体。交互体验对齐 Codex、Claude Code
这类代码智能体：用户只需要描述目标，Agent 第一次进入工程也能自行查看目录、搜索代码、阅读说明、
在用户工程内自动运行权限策略允许的命令、生成或修改文件，并根据执行结果继续工作。

产品不是“聊天框加若干固定接口”，也不要求为每个 CoreTest 功能预先绑定一个模型工具。右侧面板只是
客户端；真正的智能体循环由本地 OpenCode Runtime 承担。

```text
HK CoreTest
  -> QDockWidget + QWebEngineView 右侧面板
  -> AI Gateway（宿主鉴权、工作区注册、运行期上下文和安全代理）
  -> OpenCode 官方 Web UI + CoreTest Profile
  -> OpenCode Sidecar（会话、检索、读写、Shell、权限和模型工具调用）
  -> 唯一 CoreTest 工程目录
```

## 2. 第一性原理和边界

### Agent 自己完成的事

- 从唯一工作区根目录开始探索，不要求宿主上传每个文件。
- 使用 `glob/grep/read/LSP` 理解工程结构和调用关系。
- 根据任务创建临时分析脚本、生成代码或修改工程文件。
- 运行经过权限策略允许的测试、构建、格式化和项目 CLI。
- 阅读项目中的 `AGENTS.md`、README、SDK 源码、类型定义和示例，现学现用。
- 通过 OpenCode Skills、MCP 或 CLI 扩展能力，但不为普通项目文件建立固定业务绑定。

### 宿主必须提供的最小信息

- 一个真实、存在、经过可信 Host Connector 注册的工作区根目录。
- 当前宿主会话和工程标识。
- 文件写入、命令执行和外部访问的权限决定。
- 仅存在于 CoreTest 进程内的运行期状态，例如当前 Trace 帧、诊断 ECU 或已解析 DBC 对象。

文件、源码和磁盘上的 SDK 可以由 Agent 自己发现；CoreTest 进程内存中的对象不能被 Agent 凭空读取。
这类状态继续通过有上限的 Host Snapshot 提供，并通过已落地的 `coretest-host` 通用只读 CLI 主动查询。该桥接是运行期
数据边界，不是按问题编写固定接口。

## 3. 固定技术方案

| 层 | 采用方案 | 职责 |
| --- | --- | --- |
| CoreTest 面板 | `QDockWidget + QWebEngineView` | 显示、隐藏、停靠和宿主生命周期 |
| Agent UI | 锁定版 OpenCode Web UI + CoreTest Profile | 原生会话、工具过程、Diff、权限、历史和模型选择 |
| 宿主协议 | AI Gateway REST/OpenAPI | Bearer 鉴权、会话隔离、工作区注册和协议稳定性 |
| Agent Runtime | OpenCode `serve` | 会话、文件工具、Shell、编辑、事件流和权限系统 |
| Runtime 接口 | OpenCode OpenAPI / `@opencode-ai/sdk` | 创建会话、发送 Prompt、订阅事件、回复权限 |
| 模型 | OpenAI-compatible Provider | 复用客户的 Base URL、API Key 和模型名 |
| 汽车数据 | CoreTest 已解析对象 + `odxtools` | 确定性只读事实，不复制解析器 |
| 打包 | CoreTest + Gateway + OpenCode 独立 Sidecar | Agent 故障不影响 CAN、UDS、刷写和主进程 |

OpenCode 使用 MIT 许可证，允许商业使用和二次修改。采用它是为了复用已落地的 Agent Runtime，项目不再
自行实现一套文件搜索、编辑、Shell 工具循环、会话状态和权限系统。
正式客户交付必须遵守 `docs/14-open-source-compliance.md`：固定版本、校验产物、生成 SBOM 和第三方
Notices；完整依赖许可证审计通过前不得把 OpenCode 放入交付 ZIP。

不采用：

- CopilotKit：它是 UI/Runtime 集成方案，不是完整的工作区代码智能体；旧 assistant-ui 只保留为回退版本。
- OpenClaw：更偏个人助手、消息渠道和通用自动化，不是项目目录优先的编码 Runtime。
- OpenHands：控制中心和沙箱较重，超出单机 CoreTest 侧栏需求。
- Cline/Roo Code：主要依赖 VS Code/JetBrains 宿主。
- CLI-Anything：可作为现有软件的 CLI 适配层，但不能替代 Agent Runtime。

## 4. 工作区和安全模型

每个 Host Session 只允许注册一个工作区根目录。绝对路径只在 CoreTest Connector、Gateway 和 OpenCode
进程之间使用，不返回浏览器，不写入普通聊天消息、审计内容或模型 Prompt。
同一 Gateway 可以让多个会话共享同一个工作区；不同工作区必须启动独立 Gateway 实例，避免 Agent 串到错误工程。

工作区分为三类，不能混用：

1. **产品保护区**：CoreTest 安装目录或源码、`app/coretest_copilot`、AI Gateway、Agent UI 和 OpenCode 集成配置。该目录不能注册为 Agent 工作区，也不能通过外部目录访问或人工审批放开。
2. **用户工程工作区**：当前 CoreTest 打开的测试工程。OpenCode 以该目录为唯一 `cwd`，可自行读取、创建、修改和删除工程文件，并运行完成任务所需的项目命令。
3. **临时执行区**：模型探测、缓存和一次性中间文件使用 CoreTest 专属本机状态目录，不能承载需要交付给用户的最终修改，并随对应生命周期清理。

默认权限：

| 能力 | 默认策略 |
| --- | --- |
| 用户工程内搜索和读取 | `allow` |
| 用户工程内修改（`edit/apply_patch/write`） | `allow`，Agent 自动完成并展示 Diff |
| 用户工程内 Shell 命令 | `allow`，Agent 自动运行测试、构建、SDK、CLI 和临时脚本 |
| CoreTest/CoreTest Agent 产品源码修改 | `deny`，不能通过人工确认放开 |
| OpenCode 文件工具访问工作区外目录 | `deny` |
| OpenCode `webfetch/websearch` | `deny`，当前交付不开放 |
| Shell 子进程的操作系统文件/网络边界 | 依赖客户安装目录 ACL 和网络策略；当前不是 AppContainer 强沙盒 |
| CAN 发送、UDS、刷写、设备控制 | `deny`，不向 Agent 暴露 |

Gateway 只把可信 Connector 注册的当前用户工程交给 OpenCode。产品源码不放入工作区；工作区注册还必须拒绝明显的 CoreTest 或 CoreTest Agent 源码仓库根目录。
用户工程内常规编辑和 Shell 不再弹出逐步权限卡片；外部目录、网络和硬件能力直接拒绝。最近一轮文件变化通过 OpenCode 原生 Diff 展示；
有 Git 基线时允许按 OpenCode message revert 撤销，非 Git 工程必须明确提示无法自动撤销。
Agent 子进程继承最少环境变量，不把 Gateway Host Token、客户密钥或无关系统凭据放进 Prompt。

当前保护属于应用层工作区和工具权限，不等同于 Windows AppContainer 或独立低权限账户的操作系统强沙盒。正式客户包
必须安装到普通用户不可写目录并验收 ACL；开发机上的同用户源码目录不能作为“Shell 绝对无法越界”的安全证明。若客户要求
对任意 Shell 子进程做强制文件系统隔离，需要单独引入受限账户/AppContainer，并重新验证项目构建、SDK 和 CLI 兼容性。

## 5. 模型配置

模型来源、凭据和模型列表由 OpenCode 原生 Provider、Config 和 Auth 能力管理。Gateway 只向 WebView 暴露
受限的 Provider 列表、新增、删除、激活和连接测试接口，不开放 OpenCode 通用配置接口或 Runtime 密码。
每套 API 使用独立 Provider ID，消息发送时显式携带 `providerID + modelID`。

现有环境变量仅作为首次启动迁移来源：

```text
AI_MODEL_BASE_URL
AI_MODEL_API_KEY
AI_MODEL_NAME
```

Gateway 首次启动时把上述配置导入为默认 OpenAI-compatible Provider；后续配置持久化到 CoreTest 专属的
OpenCode 配置和 Auth 目录。API Key 不返回 WebView、不进入 Prompt，也不通过子进程环境传递。连接测试必须
通过 OpenCode 实际模型调用验证至少一次只读工具调用；仅支持普通文本补全的模型不能完成工作区 Agent 循环。
普通问答、附件、Snapshot、测试数据分析和 pytest 生成均统一进入 OpenCode，不保留旧模型回退路径。

## 6. Host Snapshot 与 SDK 使用

Host Snapshot 继续传递有上限的运行期事实：

- `trace`：时间范围、帧数、通道、方向、Frame ID、错误帧和选中帧。
- `dbc`：节点、帧、信号、单位、范围、周期和注释。
- `diagnostic`：ECU、服务、请求响应、NRC 和最近日志。
- `pdx`：诊断层、ECU 变体、服务和 CAN 收发 ID。
- `project/file`：用于 UI 展示当前选择；Agent 读取文件时直接访问工作区。

标准 SDK/CLI 的接入优先级：

1. SDK 已在项目中：Agent 阅读源码、类型和示例后直接编写调用代码。
2. 软件已有 CLI：将可执行文件加入受控 PATH，并在 `AGENTS.md` 记录常用入口。
3. 只有 SDK 没有 CLI：优先写一个薄的、可人工调用和测试的 CLI，而不是为每个函数定义 Agent Tool。
4. 只有进程内对象：复用 Host Snapshot；Agent 需要主动查询时使用 `coretest-host` 只读 CLI，不模拟 UI 点击。

当前 `coretest-host` 由 Connector 在本机随机端口提供带随机令牌的私有只读服务，Gateway 只把该连接交给
OpenCode 子进程，不返回 WebView。Agent 使用：

```text
coretest-host capabilities
coretest-host call project.summary
coretest-host call dbc.inspect --arg dbc_name=vehicle.dbc --arg frame_id=0x100
```

首版能力包括 `project.summary`、`file.inspect`、`dbc.list/inspect`、`trace.list/inspect` 和
`diagnostic.recent`。文件查询被限制在当前用户工程，DBC/Trace/诊断直接复用 CoreTest 已解析缓存；不注册
CAN 发送、UDS、刷写、设备控制或任意动态方法调用。

### OpenCode `1.18.10` 原生能力接入矩阵

| 原生能力 | 产品策略 |
| --- | --- |
| Session、消息历史、流式文本、abort | 直接接入 |
| `reasoning`、step、tool、todo、retry、patch 事件 | 直接接入并在侧栏分层呈现，不拼进最终回答 |
| `glob/grep/read/LSP/edit/write/apply_patch/bash` | 在唯一用户工程内直接接入 |
| Diff、revert | 直接接入；按 OpenCode 的 Git 基线限制展示可用性 |
| `AGENTS.md`、Skills、项目 CLI/SDK | 直接复用，由 Agent 自行发现 |
| MCP | 保留 OpenCode 原生配置能力；只接入经过产品审核的 CoreTest 通用桥，不向 WebView开放任意 MCP 安装 |
| session fork/compact/native title | 后续接入到历史会话，不在当前修复中重写第二套引擎 |
| share、web、PTY、任意外部目录 | 当前交付不开放 |
| CAN、UDS、刷写、设备控制 | 不注册为 Agent 工具 |

### Agent loop 与卡死恢复

会话内的推理、工具调用、根据工具结果继续推理、模型重试、上下文管理和任务结束判断全部由 OpenCode
原生 Agent loop 负责。Gateway 和前端不实现第二套循环，也不自行重放工具或模型请求，只处理进程和网络边界：

- Gateway 直接消费 OpenCode 的 `retry`、`session.idle`、`session.error` 和 abort 能力。
- 连续 5 分钟没有可展示的 OpenCode 会话事件，视为本轮无进展；单轮总时长最多 30 分钟。
- OpenCode SSE 在 `session.idle` 或 `session.error` 之前断开，视为异常断流，不能当作空回答或正常完成。
- 浏览器连续 5 分钟没有收到 SSE 数据时主动取消读取，并调用 Gateway abort；用户点击停止也走同一原生 abort。
- 无进展、异常断流或客户端关闭流时，Gateway 先 abort，再删除异常 OpenCode session。下一轮根据前端保存的会话历史创建新 session，避免复用损坏状态。
- 成功、失败和取消都会把仍为 `running/pending` 的 step、retry 和 todo 收口为明确终态，侧栏不永久显示转圈。

上述超时是产品内置故障策略，客户不需要配置。它们只负责终止失去进展的外围请求；OpenCode 在正常工作期间的
原生模型重试和工具循环不受影响。

## 7. 当前开发任务

### 当前状态：OpenCode 基础工作区闭环已接通，原生交互补齐进行中

实现范围：

- 已增加 OpenCode Runtime 配置、进程启动、停止和健康检查模块。
- 已增加可信 Host 工作区注册契约；校验目录真实存在并保存于服务端，不回传绝对路径。
- OpenCode 仅绑定 `127.0.0.1`，由 Gateway 管理认证信息和生命周期。
- 工程注册不启动 OpenCode；第一次 AI 请求按需启动一个进程，后续会话复用，退出 CoreTest 时关闭。
- 已把现有 OpenAI-compatible 模型配置映射为 OpenCode Provider 配置。
- Gateway 健康状态能区分“Gateway 可用”和“Agent Runtime 未安装/未启动/健康”。
- 普通问答、附件、Snapshot、测试数据分析和 pytest 生成已切换为 OpenCode 单一路径。
- UI 中的测试请求走普通 Agent 会话：先理解工程，再在用户工程中自动写入测试并运行最小相关测试；旧 `generate_test` API 仅保留兼容。
- 工程任务信息不足时，系统指令要求先读取 `AGENTS.md`、README 和项目清单，并优先复用已有 SDK、CLI、脚本和测试命令。
- Connector 已提供带随机令牌的 `coretest-host` 只读能力桥；Agent 可主动发现并调用 CoreTest 的工程、文件、DBC、Trace 和诊断查询，不依赖用户先点击对应页面。
- Host 能力桥只监听 `127.0.0.1`；地址、令牌和绝对路径不返回 WebView，OpenCode 只获得完成只读调用所需的受限运行环境。
- OpenCode 的 `cwd` 和所有 API `directory` 均指向可信 Connector 注册的用户工程；产品源码仓库根目录不能注册为工作区。
- 用户工程内 `glob/grep/read/LSP/edit/apply_patch/write/bash` 可直接使用，不再逐步审批；工作区外访问、网络和硬件控制保持拒绝。
- 侧栏会显示真实工具活动，以及最近一轮 Agent 产生的文件 Diff。
- 侧栏按已接入的 OpenCode part 类型分别显示分析过程、执行步骤、任务清单和最终 Markdown 答复；最终答复启用 GFM 表格。原生 question、完整 session 恢复和全部 part 类型仍在补齐，不能宣称 OpenCode 交互已全部完成。
- 侧栏底部固定提供模型切换、历史会话和模型/API 配置入口；历史按宿主会话保存在本机，API Key 不回显，配置更新后由 Gateway 重置 OpenCode Runtime。
- 最近一轮修改可通过 OpenCode 原生 message revert 撤销，不使用工作区级 Git reset。
- 已订阅 OpenCode SSE 事件；回答文本、工具状态和权限请求实时进入侧栏，阻塞查询接口继续保留给非聊天分析入口。
- 已复用 OpenCode 原生 Agent loop、retry、idle、error 和 abort；Gateway 与浏览器增加无进展、异常断流和客户端关闭兜底，异常会话自动丢弃并按历史重建。
- OpenCode `1.18.10` 的原生 Diff/revert 只在有 Git 基线的工作区产生快照；非 Git
  工作区仍可执行权限策略允许的编辑，侧栏会明确提示该轮无法自动撤销。
- 已用真实模型在验收工作区完成基础闭环；新的用户工程写入边界还需复验自动创建测试、运行命令、Diff 和撤销。

验收标准：

1. 单元测试能够用临时工作区和伪进程验证启动参数、工作目录、健康检查和停止。
2. Host Token 才能注册工作区，WebView Access Token 不能提交本地绝对路径。
3. 状态接口不返回工作区绝对路径、Runtime 密码或模型 API Key。
4. 在 Windows 安装 OpenCode 后，Gateway 能在指定工程目录启动 `opencode serve` 并通过
   `/global/health` 验证。
5. Gateway、Connector 和前端测试继续通过。
6. `coretest-host capabilities` 能列出只读能力，`dbc.inspect` 或 `trace.inspect` 至少一项能读取 CoreTest 已解析缓存；未知能力、目录越界和硬件能力被拒绝。

## 8. OpenCode 原生 UI 迁移顺序

继续在 assistant-ui 外壳中逐项翻译 OpenCode 事件，会长期产生协议遗漏、状态重复和交互降级。后续默认方案改为：
使用锁定版本 OpenCode 官方 Web UI 源码作为 Agent 工作台基座，构建 CoreTest 专用发行配置；Gateway 不再重写
Agent UI 状态机，只负责可信工作区、生命周期、鉴权代理、API 白名单、路径与密钥保护和 Host Bridge。

已验证 OpenCode `1.18.10` 的 `serve` 进程本身同时提供完整 Web UI、`/doc` OpenAPI、SSE 和原生 session API，
不需要额外启动第二个前端服务。当前 React/assistant-ui 侧栏保留为回退版本，原生 UI 通过验收前不删除。

### P0：已打通原生 UI 安全通路

1. **源码与构建基线**：固定 OpenCode UI tag/commit，保存源码来源、MIT License、补丁清单、前端依赖 SBOM 和构建产物哈希；Runtime 继续使用已锁定的官方 `opencode.exe`。
2. **Gateway 原生协议代理**：为 OpenCode UI 提供同源静态资源、SSE 和 HTTP 代理，由 Gateway 注入 Runtime 认证；WebView 不获得 Runtime 密码。PTY 永久禁用，因此不代理 OpenCode PTY WebSocket。
3. **固定工作区与路由白名单**：UI 只能进入 Connector 注册的唯一用户工程；阻断服务器切换、其他项目、任意目录、PTY、share、任意 MCP/OAuth、web 工具和产品源码访问。隐藏按钮不能代替服务端阻断。
4. **真实会话验收**：OpenCode 原生 question、permission、todo、retry、follow-up、fork、compact、undo/redo、Diff Review、文件引用和 context/token/cost 必须直接工作，Gateway 不再逐项复制这些状态机。

### P1：当前执行，CoreTest 发行版外观与宿主集成

5. **CoreTest Profile**：名称统一为 CoreTest Agent；替换品牌、颜色、标题和空状态，移除服务器/项目选择、更新、分享和终端入口，保留 OpenCode 原生会话、输入、工作过程和 Review 组件。
6. **响应式侧栏布局**：默认 440px 窄栏使用底部“会话/变更”Tab；允许拖拽调宽，并可一键展开到 840px 进入 OpenCode 桌面 Review 布局。宽表格横向滚动，不另写第二套 Diff UI。
7. **Host Context**：通过受控扩展点同步当前工程、选中文件、DBC、Trace、PDX 和诊断对象；进程内事实继续由 `coretest-host` 只读桥提供，不修改 OpenCode Agent loop。
8. **模型配置**：保留 CoreTest 底部模型切换和 API 配置入口，但底层直接使用 OpenCode Provider/Auth；WebView 不读取或回显 API Key。

### P2：切换与清理

9. **双通路验收**：同一锁定 Runtime 下比较现有 assistant-ui 与原生 UI 的 session、question、Diff、撤销、异常恢复和退出清理；开发分支已切换原生入口，旧壳继续作为回退直到客户验收完成。
10. **删除重复状态机**：只在切换完成后移除自研的聊天事件翻译、本地伪 session 和重复 permission/question UI；Gateway REST 宿主协议、确定性汽车数据接口和回退构建保留。

永久阻断能力仍为 `webfetch/websearch`、任意外部目录、任意 PTY 交互、session share、任意 MCP 安装、
CAN/UDS/刷写/设备控制，以及 CoreTest/CoreTest Agent/Gateway/OpenCode 集成源码修改。它们是服务端安全边界，
不能仅靠修改 OpenCode 前端隐藏。

当前 Gateway 安全代理已能只通过 Gateway 加载锁定版原生 UI、固定进入逻辑工作区并创建/列出 session；浏览器
只使用 Gateway 凭据，Runtime 密码由服务端注入。所有浏览器 `directory/workspace` 参数会被可信工作区覆盖，PTY、share、
MCP 写入/OAuth 和未列入白名单的路由由服务端拒绝，SSE 直接流式转发。CoreTest 必须等“工作区注册 → Snapshot → Context”
成功后才加载 `/agent-native/`；`/copilot-shell/` 保留为旧版回退入口。原生 Provider 目录只暴露 CoreTest 管理的条目，
新增配置只接受 OpenAI-compatible Base URL、API Key 和模型列表，任意请求头、npm Provider 和通用 Config 修改由服务端拒绝。

已完成锁定 Commit 的 UI 源码归档和逐文件校验、CoreTest Profile 源码构建、Gateway 自建静态资源托管、
前端 CycloneDX 1.6 SBOM、第三方 Notices 和全部静态资源 SHA-256。当前构建包含 99 个生产依赖组件和
864 个静态文件；零组件、未知或阻断许可证、依赖引用异常和资产哈希不一致都会阻断交付。

原生 Provider 连接测试入口和单套真实 Provider 已验证；仍未完成的是第二套真实 Provider，以及 question、Diff Review、撤销、异常恢复和真实模型流式分析的完整交互矩阵；
还需要在正式 ZIP 主窗口和干净 Windows 客户机完成离线启动、首次 API 配置、升级、ACL 和退出清理验收。Runtime 内置静态资源
只保留为构建产物缺失时的开发回退，正式交付使用 `frontend/opencode-coretest/dist` 的源码构建结果。

## 9. 当前交付顺序（基础闭环）

1. **侧栏呈现（已完成）**：工具调用、文件 Diff、模型/API、历史、窄屏布局、GFM、reasoning、step 和 todo 分层已接入。
2. **宿主上下文（已完成）**：当前选择和 Snapshot 作为会话参考数据同步，不触发重复模型回答。
3. **通用宿主能力桥（已完成基础闭环）**：`coretest-host` 可主动调用工程、文件、DBC、Trace 和诊断只读查询；不模拟点击，不向 Agent 暴露 `app.service` 源码，也不为每个按钮定义模型专用工具。真实客户分支的完整 PDX 进程内服务仍需按其非脱敏实现补充验收。
4. **项目说明（进行中）**：Agent 已优先查找工作区 `AGENTS.md`、README、SDK/CLI 和测试命令；真实用户工程仍需提供项目特定说明。
5. **通用 Agent 闭环（已完成基础闭环）**：真实模型已完成 `coretest-host`、工程写入和测试执行；仍需补齐原生 Diff 撤销、停止恢复和第二 Provider 实测。
6. **交付打包（本机已通过）**：固定 OpenCode Runtime 与 UI 源码版本，校验 ZIP/EXE/源码归档哈希，生成 Runtime 与 UI 的 SBOM/Notices，并校验 864 个 UI 静态资源；正式 ZIP 已构建并检查必需内容。
7. **交付验收（进行中）**：本机解压包可启动到工程管理页；仍需在包内人工激活工程后完成 Agent 闭环，并在干净客户机复验离线配置、升级、ACL 和退出清理。

多 Agent、RAG、飞书知识、企业 SSO、GUI 点击模拟和硬件自动控制不进入当前开发顺序。

## 10. 完成定义

产品第一版只有同时满足以下条件才算完成：

1. 用户在真实 CoreTest 右侧打开 Agent，而不是独立 IDE 或演示网页。
2. Agent 第一次进入当前工程即可自行查看架构和文件，无需逐个上传。
3. “分析这个文件”会产生可追踪的搜索、读取和必要的临时脚本执行过程，并返回引用。
4. Agent 能在用户工程中自动生成/修改文件并运行测试，同时不能修改 CoreTest、CoreTest Agent、Gateway 或 OpenCode 集成源码。
5. Agent 能根据项目说明使用至少一个已有 SDK 或 CLI，而不是预先绑定专用按钮。
6. Trace/DBC/PDX/诊断运行期数据仍通过确定性桥接得到事实，Agent 不猜测二进制格式。
7. Agent 能通过通用只读 Host CLI/MCP 主动调用至少一项 CoreTest 已有解析能力，而不是依赖用户先点击对应界面。
8. Agent 不能访问工作区外文件，也不能控制 CAN、UDS、刷写或测试设备。
9. Agent、模型或 Gateway 故障不会影响 CoreTest 主进程和硬件通信。
10. Windows 客户交付包能够重复构建、启动、退出和升级。
11. OpenCode 版本、Commit、下载来源、SBOM、第三方许可证和产物哈希完整可追溯。

## 11. 固定验证

```powershell
$node='C:\Users\humin\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
$pnpm='C:\Users\humin\.cache\codex-runtimes\codex-primary-runtime\dependencies\bin\fallback\pnpm.cmd'
$env:Path=(Split-Path -Parent $node) + [IO.Path]::PathSeparator + $env:Path

cd D:\geely-ai-platform\src\ai-gateway
$env:PYTHONPATH='src'
python -m unittest discover -s tests -p "test_*.py"
python evals\run_eval.py

cd D:\geely-ai-platform\frontend\copilot-shell
& $pnpm typecheck
& $pnpm build

cd D:\geely-ai-platform\samples\host-integration
python -m unittest discover -s . -p "test_*.py"

cd D:\geely-ai-platform\integrations\coretest
$env:PYTHONPATH='.'
python -m unittest discover -s tests -p "test_*.py"

cd D:\geely-ai-platform
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build-opencode-ui.ps1 -Node $node -Pnpm $pnpm
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\generate-opencode-ui-compliance.ps1 -Node $node -Pnpm $pnpm
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-ai-gateway.ps1
$env:CORETEST_PROJECT_ROOT='D:\geely-ai-platform\customer-data\hk-coretest-ai\test\project\test'
python .\integrations\coretest\smoke_test.py
git diff --check
```

真实模型闭环在同一脚本中通过 `CORETEST_SMOKE_PROMPT` 开启；需要验证 Agent 确实执行了工具时，同时设置
`CORETEST_SMOKE_REQUIRE_TOOL=1`。功能验收读取 Qt 状态、Gateway API、OpenCode 会话结果和 activity；截图只做最终视觉抽查。

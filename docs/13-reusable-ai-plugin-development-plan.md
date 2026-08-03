# CoreTest 工作区智能体产品开发计划

## 1. 产品定义

本项目交付的是嵌入 HK CoreTest 右侧的本地工作区智能体。交互体验对齐 Codex、Claude Code
这类代码智能体：用户只需要描述目标，Agent 第一次进入工程也能自行查看目录、搜索代码、阅读说明、
运行获批命令、生成或修改文件，并根据执行结果继续工作。

产品不是“聊天框加若干固定接口”，也不要求为每个 CoreTest 功能预先绑定一个模型工具。右侧面板只是
客户端；真正的智能体循环由本地 OpenCode Runtime 承担。

```text
HK CoreTest
  -> QDockWidget + QWebEngineView 右侧面板
  -> React + assistant-ui + Fluent UI
  -> AI Gateway（宿主鉴权、工作区注册、运行期上下文和协议适配）
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
这类状态继续通过有上限的 Host Snapshot 提供，或后续封装为一个通用只读 CLI/MCP 服务。该桥接是运行期
数据边界，不是按问题编写固定接口。

## 3. 固定技术方案

| 层 | 采用方案 | 职责 |
| --- | --- | --- |
| CoreTest 面板 | `QDockWidget + QWebEngineView` | 显示、隐藏、停靠和宿主生命周期 |
| Agent UI | React + assistant-ui + Fluent UI | 消息、工具步骤、Diff、权限请求和取消操作 |
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

- CopilotKit：它是 UI/Runtime 集成方案，不是完整的工作区代码智能体，本项目已使用 assistant-ui。
- OpenClaw：更偏个人助手、消息渠道和通用自动化，不是项目目录优先的编码 Runtime。
- OpenHands：控制中心和沙箱较重，超出单机 CoreTest 侧栏需求。
- Cline/Roo Code：主要依赖 VS Code/JetBrains 宿主。
- CLI-Anything：可作为现有软件的 CLI 适配层，但不能替代 Agent Runtime。

## 4. 工作区和安全模型

每个 Host Session 只允许注册一个工作区根目录。绝对路径只在 CoreTest Connector、Gateway 和 OpenCode
进程之间使用，不返回浏览器，不写入普通聊天消息、审计内容或模型 Prompt。
同一 Gateway 可以让多个会话共享同一个工作区；不同工作区必须启动独立 Gateway 实例，避免 Agent 串到错误工程。

默认权限：

| 能力 | 默认策略 |
| --- | --- |
| 工作区内搜索和读取 | `allow` |
| 工作区内创建、编辑、应用补丁 | 当前 `deny`；权限 UI 完成后改为 `ask` |
| Shell 命令 | 当前 `deny`；权限 UI 完成后改为 `ask` |
| 工作区外文件访问 | `deny` |
| 网络访问 | `ask` 或由客户部署策略关闭 |
| CAN 发送、UDS、刷写、设备控制 | `deny`，不向 Agent 暴露 |

权限请求必须展示具体工具、命令或目标文件。用户可以仅允许一次；第一版不提供宽泛的“永远允许全部”。
Agent 子进程继承最少环境变量，不把 Gateway Host Token、客户密钥或无关系统凭据放进 Prompt。

## 5. 模型配置

现有配置继续作为客户侧唯一模型来源：

```text
AI_MODEL_BASE_URL
AI_MODEL_API_KEY
AI_MODEL_NAME
```

Gateway 在启动 OpenCode 时生成对应的 OpenAI-compatible Provider 配置，并通过本机鉴权接口单独写入 Key，
不把 Key 传给子进程环境。模型必须可靠支持工具调用；仅支持普通文本补全的模型不能完成工作区 Agent 循环。
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
4. 只有进程内对象：复用 Host Snapshot；确有交互需求时再做只读 MCP/CLI 桥。

## 7. 当前开发任务

### 当前状态：OpenCode 工作区操作闭环已接入

实现范围：

- 已增加 OpenCode Runtime 配置、进程启动、停止和健康检查模块。
- 已增加可信 Host 工作区注册契约；校验目录真实存在并保存于服务端，不回传绝对路径。
- OpenCode 仅绑定 `127.0.0.1`，由 Gateway 管理认证信息和生命周期。
- 工程注册不启动 OpenCode；第一次 AI 请求按需启动一个进程，后续会话复用，退出 CoreTest 时关闭。
- 已把现有 OpenAI-compatible 模型配置映射为 OpenCode Provider 配置。
- Gateway 健康状态能区分“Gateway 可用”和“Agent Runtime 未安装/未启动/健康”。
- 普通问答、附件、Snapshot、测试数据分析和 pytest 生成已切换为 OpenCode 单一路径。
- `glob/grep/read/LSP` 可直接使用；`edit` 和 Shell 每次操作都需要用户批准。
- 已禁用会绕过审批的 `apply_patch/write`，工作区外访问和硬件控制保持拒绝。
- 侧栏会显示真实工具活动，以及最近一轮 Agent 产生的文件 Diff。
- 最近一轮修改可通过 OpenCode 原生 message revert 撤销，不使用工作区级 Git reset。
- 已订阅 OpenCode SSE 事件；回答文本、工具状态和权限请求实时进入侧栏，阻塞查询接口继续保留给非聊天分析入口。
- OpenCode `1.18.10` 的原生 Diff/revert 只在有 Git 基线的工作区产生快照；非 Git
  工作区仍可执行获批编辑，但下一阶段必须在侧栏明确提示该轮不可撤销。

验收标准：

1. 单元测试能够用临时工作区和伪进程验证启动参数、工作目录、健康检查和停止。
2. Host Token 才能注册工作区，WebView Access Token 不能提交本地绝对路径。
3. 状态接口不返回工作区绝对路径、Runtime 密码或模型 API Key。
4. 在 Windows 安装 OpenCode 后，Gateway 能在指定工程目录启动 `opencode serve` 并通过
   `/global/health` 验证。
5. Gateway、Connector 和前端测试继续通过。

## 8. 后续交付顺序

1. **侧栏呈现**：继续打磨工具调用、文件 Diff、权限确认和窄屏布局。
2. **宿主上下文**：把当前选择和 Snapshot 作为会话上下文注入，不触发重复模型回答。
3. **项目说明**：为 CoreTest 工作区提供最小 `AGENTS.md`，记录安全边界、测试命令和现成 SDK/CLI。
4. **真实验收**：完成“分析任意工程文件”“生成并运行获批测试”“调用项目已有 SDK/CLI”三个闭环。
5. **交付打包**：固定 OpenCode 版本，纳入 Windows 交付包，验证端口冲突、退出、升级和离线配置。
6. **交付验收**：验证所有 AI 入口均只走 OpenCode，确定性汽车数据代码只提供事实。

多 Agent、RAG、飞书知识、企业 SSO、GUI 点击模拟和硬件自动控制不进入当前开发顺序。

## 9. 完成定义

产品第一版只有同时满足以下条件才算完成：

1. 用户在真实 CoreTest 右侧打开 Agent，而不是独立 IDE 或演示网页。
2. Agent 第一次进入当前工程即可自行查看架构和文件，无需逐个上传。
3. “分析这个文件”会产生可追踪的搜索、读取和必要的临时脚本执行过程，并返回引用。
4. Agent 能在审批后生成/修改工作区文件并运行测试；拒绝时不会绕过权限。
5. Agent 能根据项目说明使用至少一个已有 SDK 或 CLI，而不是预先绑定专用按钮。
6. Trace/DBC/PDX/诊断运行期数据仍通过确定性桥接得到事实，Agent 不猜测二进制格式。
7. Agent 不能访问工作区外文件，也不能控制 CAN、UDS、刷写或测试设备。
8. Agent、模型或 Gateway 故障不会影响 CoreTest 主进程和硬件通信。
9. Windows 客户交付包能够重复构建、启动、退出和升级。
10. OpenCode 版本、Commit、下载来源、SBOM、第三方许可证和产物哈希完整可追溯。

## 10. 固定验证

```powershell
cd D:\geely-ai-platform\src\ai-gateway
$env:PYTHONPATH='src'
python -m unittest discover -s tests -p "test_*.py"
python evals\run_eval.py

cd D:\geely-ai-platform\frontend\copilot-shell
pnpm typecheck
pnpm build

cd D:\geely-ai-platform\samples\host-integration
python -m unittest discover -s . -p "test_*.py"

cd D:\geely-ai-platform\integrations\coretest
$env:PYTHONPATH='.'
python -m unittest discover -s tests -p "test_*.py"

cd D:\geely-ai-platform
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-ai-gateway.ps1
git diff --check
```

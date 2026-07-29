# CoreTest AI Copilot 产品开发计划

## 1. 最终产品

本项目交付的是可嵌入汽车测试软件和网站的 AI Copilot。第一个正式宿主是
HK CoreTest。产品不是通用聊天平台，也不替代测试软件、AnythingLLM 或设备控制系统。

```text
CoreTest / 其他宿主
  -> 右侧 Copilot WebView
  -> Host Connector（当前项目、页面、选择和结构化快照）
  -> 本地 AI Gateway Sidecar（稳定 REST API）
  -> 确定性分析工具 + 文件问答/测试代码生成 + 可配置模型
```

用户应能在 CoreTest 中打开右侧 Copilot，选择工程中的 PDX、Trace、DBC 帧或诊断 ECU 后直接提问。
Copilot 必须知道用户当前正在看什么，先用确定性代码计算事实，再由模型解释结果并给出引用。
用户添加代码、配置或数据文件后，可以让模型基于文件内容回答问题并生成 pytest 测试模块；生成代码只在用户点击保存后进入当前项目的 `generated_tests`，不自动执行。

## 2. 产品边界

第一版必须提供：

- CoreTest 原生右侧可停靠面板，可显示、隐藏和调整宽度。
- Gateway 由宿主管理启动、健康检查、异常提示和退出清理。
- 每个宿主窗口使用独立 `host_session_id`，上下文不串线。
- 当前项目、主页面、子页面、文件、DBC 节点/帧、Trace 帧、诊断 ECU 自动同步。
- PDX、Trace、DBC、诊断日志的结构化分析。
- 真正的多轮对话、新建对话和运行期历史会话；可切换回同一 CoreTest 工程的旧会话，工程之间严格隔离。
- 最多添加 5 个文本文件，支持普通问答和基于附件生成 pytest。
- 生成代码在对话中完整预览，可复制，可由用户明确保存到 `generated_tests`。
- OpenAI-compatible 模型按客户环境配置。
- 所有 API 回答带 `request_id`，界面仅在故障排查时展示；知识结论带来源引用。
- Gateway、WebView 和 Host Connector 均不得把客户绝对路径或密钥展示给浏览器。

第一版禁止：

- 发送 CAN 报文、启动回放、执行 UDS、刷写 ECU 或控制硬件通道。
- 修改业务源码、SQLite 配置、测试配置或客户知识库；`generated_tests` 是唯一允许的生成写入目录。
- 自动执行生成代码，或让模型直接编辑任意项目文件。
- 把百万条原始帧或完整 PDX 直接发送给模型。
- 自行补写 PDX/ODX 解析器，或执行 PDX 容器中的脚本。
- 引入 Agent 框架、多 Agent、工作流引擎、向量数据库、动态 UI 或第二套聊天框架。

## 3. 已确认的客户软件事实

目标源码：

```text
https://jihulab.com/hk-group/hk-coretest-ai.git
commit e27752a834b4dd8cfb1f2d4df7c8f45dc516cece
```

CoreTest 使用 Python、PySide6、SQLModel/SQLite、PyInstaller 和 pyqtgraph。主窗口是
`QMainWindow + QTabWidget`，现有服务已经解析 DBC、ASC/BLF Trace，并通过 Qt Signal 暴露
项目和诊断事件。集成必须复用这些服务，不能在 Gateway 中复制解析器。

PDX 是 ODX 诊断描述数据库，描述 ECU、DID、DTC、诊断服务和协议参数，不是测试结果。
当前极狐提交是脱敏分支，`project_pdx_service.py` 只有接口壳，不能作为正式 PDX 实现。仓库中的
`somersault.pdx` 已验证为 ODX 2.2 样例，使用成熟开源库 `odxtools` 解析 ECU、诊断层、服务和 CAN
通信参数；不执行 PDX 内嵌脚本，也不把完整 PDX 发送给模型。PDX 用于解释诊断能力和后续 Trace/
诊断结果，不输出 `TestRunSummary`。

## 4. 固定技术方案

| 层 | 采用方案 | 原因 |
| --- | --- | --- |
| CoreTest 面板 | `QDockWidget + QWebEngineView` | Qt 原生停靠体验，复用 Web 前端 |
| Host Connector | Python + Qt Signal + 标准库 HTTP | 与 CoreTest 同语言，最小改造 |
| Copilot UI | React + assistant-ui + Fluent UI | 复用成熟对话、原生附件、Markdown 和 Microsoft 风格组件 |
| 集成协议 | AI Gateway REST/OpenAPI | 与宿主语言、UI 和模型框架解耦 |
| 分析 | CoreTest 已解析对象 + Gateway 确定性统计 | 避免 LLM 算数和重复解析 |
| PDX | `odxtools` | 直接复用 ASAM ODX/PDX 成熟解析能力，不自研格式解析器 |
| 模型 | 官方 `openai-python` + OpenAI-compatible API | 由客户选择部署和密钥，覆盖 Responses / Chat Completions |
| 打包 | CoreTest PyInstaller + Gateway 独立 Sidecar | AI 故障不影响硬件通信主进程 |

不采用 AnythingLLM、Open WebUI、LibreChat 作为核心运行时：它们是完整聊天/知识产品，会额外引入用户、存储、权限和部署面。Cline、Continue、OpenHands 是具文件写入和命令执行能力的开发代理，不符合 CoreTest 的只读安全边界。CopilotKit 需要其专用 Runtime；当前以 assistant-ui 的可替换 Runtime 满足嵌入需求。

## 5. 数据契约

Host Context 只保存轻量定位信息：

```json
{
  "host_application": "HK CoreTest",
  "project_id": "project-name",
  "current_view": "TRACE / 实时CAN TRACE",
  "selection_kind": "can_trace_frame",
  "selection_label": "0x123 RX",
  "snapshot_revision": "42"
}
```

Host Snapshot 保存有上限的结构化事实，不保存原始大文件：

- `trace`：时间范围、总帧数、通道/方向/Frame ID 分布、错误帧和选中帧。
- `dbc`：文件、节点、帧、信号、单位、范围、发送周期和注释。
- `diagnostic`：ECU、服务、请求/响应、正负响应、NRC 和最近日志。
- `pdx`：文件、诊断层、ECU 变体、诊断服务和 CAN 收发 ID。
- `project`：项目名、支持文件清单和当前任务状态。

默认单个 Snapshot 不超过 1 MiB，列表按 Top-N 或最近 N 条裁剪。Gateway 只接受 JSON 兼容值，
拒绝未知类型和超限内容。

## 6. 交付阶段和验收

### P0-A：文档与产品范围收敛

- 删除重复、过期和过程性开发文档。
- README 只保留产品入口、启动、测试和三份有效文档。
- 本文成为唯一任务优先级和成品完成标准。

### P0-B：CoreTest 宿主集成

- `integrations/coretest` 提供可复制到客户仓库的最小插件模块和安装脚本。
- CoreTest 主窗口右侧显示 Copilot Dock，菜单/按钮可开关。
- Host Connector 启动或连接 Gateway，加载会话化 WebView URL。
- 项目和标签页切换自动更新 Host Context。
- 主窗口关闭时释放 Session，并只终止由本窗口启动的 Gateway。
- Gateway 不可用时面板显示可重试错误，不阻塞 CoreTest 主界面。

### P0-C：真实数据闭环

- 新增 Host Snapshot REST 契约、大小限制、会话隔离、审计和测试。
- Trace 当前视图能输出确定性摘要；快捷按钮和自然语言均可分析。
- DBC 当前节点/帧能输出字段和信号语义；不重新解析 DBC。
- 诊断日志能统计正负响应和 NRC；不触发诊断操作。
- 在工程树选中 PDX 后，使用 `odxtools` 发布有上限的结构化摘要并可直接提问。
- 未配置模型时仍返回可用的确定性中文分析。

### P0-C2：文件到测试代码闭环

- `/api/v1/copilot/query` 支持普通问答和 `generate_test` 两种任务。
- 浏览器只上传当前请求需要的 UTF-8 文本内容，不把附件写入 Gateway 或知识库。
- 单文件不超过 256 KiB，总计不超过 512 KiB；拒绝路径、二进制和未知字段。
- 未配置模型时返回明确错误和 `request_id`，不生成假代码。
- 生成结果必须是可预览、可复制、可保存的 Python 测试模块；保存由用户显式触发。

### P0-C3：侧栏会话体验

- 顶部操作在 320–520 px Dock 宽度内保持固定尺寸；悬停、加载图标切换和点击时不得位移或抖动。
- 当前 CoreTest 运行期间提供工程内历史列表，可新建、切换并继续旧会话；标题取首条用户消息，并显示更新时间和消息数。
- 会话与 `host_application + project_id` 绑定，切换工程后自动打开该工程最近会话，不得带入其他工程的消息或生成物。
- 模型请求期间锁定会话切换；响应必须写回请求发起时的会话，不能因界面切换写错位置。
- 第一版历史只保存在当前 WebView 内存中。未确认保留周期、权限和加密策略前，不把客户对话、代码、日志或附件内容写入磁盘或浏览器持久存储。
- 关闭 CoreTest 或重新加载 WebView 后不承诺恢复历史；跨进程恢复属于 P1，不能以牺牲客户数据边界为代价提前实现。

### P0-D：可交付构建

- Gateway 单测、eval、Host SDK 测试、前端 typecheck/build 全部通过。
- CoreTest Connector 单测不依赖硬件。
- 实际启动 CoreTest，截图验证 Dock 非空、无重叠、可调整宽度。
- PyInstaller 构建验证 Qt WebEngine、Gateway Sidecar、前端静态资源和 REST 契约资源路径。
- 启动、健康检查、退出和端口冲突均有可重复验证。
- 客户机器只需配置模型/Token，不修改业务代码。

### P1：有真实输入后开发

- 提供质量规则和阈值后，增加规则判定。
- 取得真实知识库权限、检索质量和数据规模后，选择成熟知识产品或索引式 RAG。
- 提供 OIDC/OAuth2 参数后，接企业身份平台。
- 明确跨进程恢复要求后，再持久化会话。

## 7. 完成定义

产品第一版只有同时满足以下条件才算完成：

1. 用户在真实 CoreTest 中打开右侧 Copilot，而不是只看 `/showcase`。
2. 选择 PDX/Trace/DBC/诊断对象后，Copilot 显示正确上下文并能直接分析实际内容。
3. 添加代码或配置文件后，能够问答并通过已配置模型生成可保存的 pytest 测试模块。
4. 至少三类真实数据能得到确定性结果和自然语言解释。
5. AI 故障不会影响 CAN、UDS、刷写和项目管理功能。
6. 除用户明确保存到 `generated_tests` 外，无 AI 写操作或设备控制入口。
7. 安装、配置、启动和升级步骤可重复执行。
8. 自动测试与一次真实桌面验证均通过。

演示页、Mock CSV、接口壳、Spike 或“以后替换”的实现不能单独标记为产品完成。

## 8. 固定验证

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
python -m unittest discover -s tests -p "test_*.py"
```

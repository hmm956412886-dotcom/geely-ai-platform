# AGENTS.md

本文件约束本项目内的 AI 编码行为。目标是先做出可展示、可集成、可复用的 AI 插件底座，再逐步补真实能力。

## 0. 当前主计划

后续对话或新 AI 接手时，必须先读：

1. `docs/13-reusable-ai-plugin-development-plan.md`
2. `docs/04-development-guide.md`
3. `README.md`
4. 涉及 OpenCode 构建或客户交付时，再读 `docs/14-open-source-compliance.md`

当前唯一产品目标是：

```text
在真实 HK CoreTest 中交付可运行的右侧工作区智能体：像 Codex 一样理解工程、分析文件、生成代码并在审批后执行工作区操作
```

方向：保留 CoreTest Qt Dock、assistant-ui + Fluent UI、Gateway REST API 和分级 Bearer 鉴权；引入 MIT 许可的 OpenCode 作为本地工作区 Agent Sidecar。Gateway 负责可信工作区注册、生命周期、鉴权和宿主数据桥接，OpenCode 负责检索、读写、命令执行、会话和工具调用。现有确定性 PDX/Trace/DBC/诊断分析继续保留，不重复实现。

## 1. 先想清楚再写代码

- 新功能先写计划、边界和验收标准，再写代码。
- 文档用于约束未来开发，不是代码完成后的补丁说明。
- 不要假设客户软件内部实现；没有源码时，以 HTTP、WebView、CLI、文件契约为准。
- 有多种理解时，先说清楚取舍。
- 不清楚 PDX 等测试文件格式时，不猜格式；优先让 Agent 阅读项目说明并使用官方工具、SDK、CLI 或客户导出能力。
- 每个任务先定义可验收结果。

## 2. 简单优先

- 能用标准库，就用标准库。
- 有成熟开源项目或官方 SDK，就优先复用，不从 0 自研。
- 不为单次使用写抽象。
- 不提前做多 Agent、向量库迁移、复杂工作流引擎或第二套聊天 UI。
- MVP 只保留能展示、能集成、能验证的代码。

## 3. 改动要克制

- 只改和当前任务直接相关的文件。
- 不顺手重构无关代码。
- 不提交客户真实数据、PDX、日志、密钥或本地缓存。
- `.codegraph/`、`__pycache__/`、测试大文件不进入 Git。

## 4. 当前交付范围

- 真实 CoreTest 主窗口中的右侧 AI Copilot。
- Gateway 和 OpenCode Sidecar 的启动、健康检查、会话释放和故障隔离。
- Gateway REST/OpenAPI 和 Plugin Manifest 作为稳定宿主协议。
- 每个宿主会话只注册一个可信工作区根目录，绝对路径不返回 WebView。
- Agent 可自行搜索、读取和理解工作区；写文件和执行命令必须经过权限策略。
- 项目内已有 SDK、CLI、说明文档和脚本由 Agent 按需发现和使用，不为每个功能编写固定绑定。
- 当前工程、选中文件、PDX、DBC、Trace 和诊断对象继续作为宿主运行期上下文同步。
- PDX、Trace、DBC 和诊断日志的确定性只读分析。
- 客户部署包可重复构建，并在真实 CoreTest 和干净 Windows 环境验收。
- OpenCode 客户 Runtime 必须匹配 `config/open-source-lock.json` 的锁定版本；SBOM、第三方许可证和 Notices 未通过时禁止打包。

暂不做：

- 控制测试设备。
- 未经审批修改工作区文件或执行命令。
- 访问已注册工作区以外的文件。
- 让 Agent 直接调用 CAN 发送、UDS、刷写或设备控制能力。
- 全量迁移飞书知识库。
- 没有真实需求的复杂业务工具绑定。

## 5. 开源复用优先级

- Copilot 前端：继续使用 assistant-ui External Store Runtime 和 Fluent UI，不引入 CopilotKit 或第二套聊天框架。
- Agent 运行时：使用 OpenCode `serve` + OpenAPI/SDK，不自行实现文件搜索、编辑、命令循环和会话引擎。
- 模型：把现有 OpenAI-compatible Base URL、API Key 和模型名映射到 OpenCode Provider；迁移期间保留现有 `openai-python` 确定性分析调用。
- Agent 扩展：优先使用项目 `AGENTS.md`、Skills、现成 CLI 和 SDK；只有进程内实时状态才通过 Host Snapshot 或通用 CLI/MCP 桥接。
- 汽车数据：复用 CoreTest 已解析对象和 `odxtools`，不在 Gateway 重复实现解析器。
- 知识/RAG：不属于当前交付范围，不能提前建设。

## 6. 验证

每个非平凡改动至少运行对应测试。

常用命令：

```powershell
cd D:\geely-ai-platform\src\ai-gateway
$env:PYTHONPATH='src'
python -m unittest discover -s tests -p "test_*.py"
```

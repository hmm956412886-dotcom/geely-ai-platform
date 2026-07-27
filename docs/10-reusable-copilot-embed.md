# 可复用 Copilot 嵌入契约

## 1. 结论

`/copilot` 是可复用的 AI 侧边栏组件，不能绑定某一个业务软件页面。

它可以被嵌入到：

- 汽车测试软件 WebView。
- 公司内部网站。
- 项目管理平台。
- 后续其他桌面软件或 Web 系统。

白话备注：我们不要给每个软件重新做一个 AI 面板。每个宿主只负责告诉 AI “我现在在哪、看什么数据”，同一个 Copilot 面板负责展示、提问和工具调用。

## 2. 嵌入方式

Web / 公司网站：

```html
<iframe
  title="Geely AI Copilot"
  src="http://127.0.0.1:8765/copilot"
  style="width: 440px; height: 100vh; border: 0"
></iframe>
```

桌面软件 WebView：

```text
http://127.0.0.1:8765/copilot
```

产品演示页：

```text
http://127.0.0.1:8765/showcase
```

`/showcase` 只是演示宿主软件如何嵌入 `/copilot`，不是另一个正式 Copilot。

## 3. 宿主上下文

宿主系统在打开或刷新 Copilot 前，调用：

```http
POST /api/v1/host/context
Content-Type: application/json
```

```json
{
  "project_id": "GEELY_TEST",
  "run_id": "RUN_001",
  "source_file": "D:\\test-results\\run_001.csv",
  "target_file": "D:\\test-results\\run_000.csv",
  "current_view": "test_result_detail",
  "user_id": "tester"
}
```

Copilot 自己读取：

```http
GET /api/v1/host/context
```

白话备注：这就是“上下文注入”。AI 面板不需要知道宿主软件内部代码，只要拿到当前项目、当前 Run、当前文件路径，就能工作。

## 4. 复用边界

Copilot 只负责：

- 展示消息流。
- 读取 Host Context。
- 调用 `/api/v1/tools` 中声明的工具。
- 展示分析结果、引用和 `request_id`。

宿主系统负责：

- 决定在哪里显示侧边栏。
- 提供当前上下文。
- 管理用户身份和权限。
- 控制是否允许高风险工具。

## 5. 后续升级

当前 MVP 先用无依赖 HTML/CSS/JS，保证可展示、可嵌入。

后续如果要做正式前端工程，再考虑：

- `assistant-ui`：成熟 Chat UI 组件。
- `CopilotKit`：更完整的 Copilot / Agent UI。
- `AG-UI`：Agent 与前端交互协议。

原则不变：前端框架可以替换，`/copilot`、`/api/v1/host/context`、`/api/v1/tools` 这三个契约不要轻易变。

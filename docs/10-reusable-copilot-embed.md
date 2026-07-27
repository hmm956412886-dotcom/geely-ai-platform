# 可复用 Copilot 嵌入契约

## 1. 产品入口

同一个 React + CopilotKit 侧边栏用于公司网站 iframe 和桌面软件 WebView：

```text
http://127.0.0.1:8765/copilot-shell/?host_session_id=<宿主会话ID>&host_origin=<宿主网页Origin>
```

`host_session_id` 由宿主创建。同一个侧边栏实例保持不变，不同网站页面、桌面窗口或测试任务使用不同会话，避免上下文串线。

产品演示入口：

```text
http://127.0.0.1:8765/showcase
```

## 2. 网站 iframe

```html
<iframe
  id="geely-ai-copilot"
  title="Geely AI Copilot"
  src="http://127.0.0.1:8765/copilot-shell/?host_session_id=run-001&amp;host_origin=https%3A%2F%2Fintranet.example.com"
  style="width: 460px; height: 100vh; border: 0"
></iframe>
```

Copilot 加载后会发送 `geely-ai.copilot-ready`。宿主使用同源 `postMessage` 更新当前上下文：

```js
const copilot = document.getElementById("geely-ai-copilot");

copilot.contentWindow.postMessage(
  {
    type: "geely-ai.host-context",
    host_session_id: "run-001",
    context: {
      project_id: "GEELY_TEST",
      run_id: "RUN_001",
      source_asset_id: "current-run",
      target_asset_id: "baseline-run",
      current_view: "test_result_detail",
      user_id: "tester"
    }
  },
  "http://127.0.0.1:8765"
);
```

`host_origin` 必须是宿主网页的精确 Origin，例如 `https://intranet.example.com`。Gateway 与宿主经反向代理保持同源时可以省略。生产环境的 `host_session_id` 应使用不可预测的 UUID。

## 3. 本地文件

浏览器不传本地绝对路径。桌面宿主、Sidecar 或 Host SDK 先注册文件：

```http
POST /api/v1/host/assets?host_session_id=run-001
Content-Type: application/json

{
  "asset_id": "current-run",
  "file_path": "D:\\test-results\\run_001.csv"
}
```

Gateway 只向浏览器返回 `asset_id`、文件名、类型和大小，真实路径只保存在当前 Gateway 进程内。

## 4. 桌面 WebView / Host SDK

桌面软件可直接打开会话化 URL，并使用 `samples/host-integration/python_host_sdk.py` 完成：

- 创建 `host_session_id`。
- 注册本地 CSV / JSON 为 `asset_id`。
- 更新当前项目、Run 和视图上下文。
- 调用只读分析、洞察和对比接口。

稳定集成协议仍是 Gateway REST API；`postMessage` 只负责 iframe/WebView 的上下文同步。

## 5. 集成契约

```text
/plugin-manifest.json
/openapi.json
/api/v1/tools
```

宿主负责身份、权限、侧边栏位置和会话生命周期。Copilot 负责读取上下文、调用只读工具并展示结果与 `request_id`。

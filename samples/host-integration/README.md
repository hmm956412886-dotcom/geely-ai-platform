# Host Integration Sample

这个目录演示“宿主测试软件如何接入 AI Gateway”。它不需要客户软件源码，只用 HTTP 调用模拟宿主软件的插件按钮。

真正集成时，宿主先注册本地文件取得 `asset_id`，再把会话上下文传给 AI Gateway，最后打开带 `host_session_id` 的 `/copilot-shell/` 或展示返回结果。

## 1. 启动 AI Gateway

```powershell
cd D:\geely-ai-platform\src\ai-gateway
$env:PYTHONPATH='src'
python -m ai_gateway.server --port 8765
```

## 2. 运行宿主集成样例

另开一个 PowerShell：

```powershell
cd D:\geely-ai-platform
.\samples\host-integration\invoke-ai-gateway.ps1
```

同时打开 Copilot 面板：

```powershell
.\samples\host-integration\invoke-ai-gateway.ps1 -OpenCopilot
```

使用真实导出文件：

```powershell
.\samples\host-integration\invoke-ai-gateway.ps1 `
  -ProjectId "GEELY_TEST" `
  -RunId "RUN_20260727_001" `
  -SourceFile "D:\test-results\run_001.csv" `
  -TargetFile "D:\test-results\run_000.csv"
```

## 3. 使用 Python Host SDK

如果宿主软件插件、内部服务或自动化脚本使用 Python，可以直接复用这个最小 SDK：

```powershell
cd D:\geely-ai-platform\samples\host-integration
python .\host_connector_demo.py --gateway-url http://127.0.0.1:8765
```

核心调用方式：

```python
from python_host_sdk import GeelyAIGatewayClient, HostContext

client = GeelyAIGatewayClient("http://127.0.0.1:8765")
source_asset_id = client.register_asset(r"D:\test-results\run_001.csv")["result"]["asset_id"]
target_asset_id = client.register_asset(r"D:\test-results\run_000.csv")["result"]["asset_id"]
context = HostContext(
    project_id="GEELY_TEST",
    run_id="RUN_001",
    source_asset_id=source_asset_id,
    target_asset_id=target_asset_id,
    user_id="tester",
)

client.update_host_context(context)
analysis = client.analyze(source_asset_id=source_asset_id, question="分析失败原因")
insights = client.insights(source_asset_id=source_asset_id)
compare = client.compare(baseline_asset_id=source_asset_id, target_asset_id=target_asset_id)
```

白话备注：SDK 不做 AI，只负责把宿主软件的“当前上下文”和“按钮动作”稳定地转成 HTTP 调用。C#、Java、C++ 插件也可以照这个类的接口移植。

## 4. 样例做了什么

1. `GET /health` 检查 AI Gateway 是否可用。
2. `POST /api/v1/host/assets` 把本地文件注册为浏览器安全的 `asset_id`。
3. `POST /api/v1/host/context?host_session_id=...` 写入当前项目、Run、资产和用户。
4. `GET /api/v1/tools` 读取 Agent / SK 可调用的工具契约。
5. `POST /api/v1/analyze` 分析当前测试文件。
6. `POST /api/v1/test-data/insights` 生成状态分布和 Top 失败原因。
7. `POST /api/v1/test-data/compare` 对比两次测试结果。
8. 可选打开 `/copilot-shell/?host_session_id=...` 侧边栏面板。

## 5. 客户软件怎么替换

如果客户软件能写插件或按钮，把脚本里的 HTTP 调用换成客户软件语言即可。

最小集成顺序：

```text
客户软件按钮点击
  -> POST /api/v1/host/assets
  -> POST /api/v1/host/context?host_session_id=...
  -> POST /api/v1/analyze
  -> 显示 answer / data / citations / request_id
```

如果客户软件支持 WebView：

```text
客户软件右侧面板
  -> 打开 http://127.0.0.1:8765/copilot-shell/?host_session_id=...
```

如果客户软件暂时只能导出文件：

```text
导出 CSV / JSON / 后续 PDX
  -> 把文件路径传给 -SourceFile
  -> AI Gateway 只读分析
```

## 6. 当前边界

- 只读分析，不修改测试配置。
- 不控制测试设备。
- 不写客户数据库。
- 模型 API Key 由客户环境变量配置，不放进脚本。
- PDX 先等真实样例或官方工具确认后再接 Adapter。

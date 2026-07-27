# Host Integration Sample

这个目录演示“宿主测试软件如何接入 AI Gateway”。它不需要客户软件源码，只用 HTTP 调用模拟宿主软件的插件按钮。

白话备注：真正集成时，客户软件要做的事情和这个脚本一样：先把当前测试上下文传给 AI Gateway，再调用分析接口，最后打开 `/copilot` 或展示返回结果。

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

## 3. 样例做了什么

1. `GET /health` 检查 AI Gateway 是否可用。
2. `POST /api/v1/host/context` 写入当前项目、Run、文件路径和用户。
3. `GET /api/v1/tools` 读取 Agent / SK 可调用的工具契约。
4. `POST /api/v1/analyze` 分析当前测试文件。
5. `POST /api/v1/test-data/compare` 对比两次测试结果。
6. 可选打开 `/copilot` 侧边栏面板。

## 4. 客户软件怎么替换

如果客户软件能写插件或按钮，把脚本里的 HTTP 调用换成客户软件语言即可。

最小集成顺序：

```text
客户软件按钮点击
  -> POST /api/v1/host/context
  -> POST /api/v1/analyze
  -> 显示 answer / data / citations / request_id
```

如果客户软件支持 WebView：

```text
客户软件右侧面板
  -> 打开 http://127.0.0.1:8765/copilot
```

如果客户软件暂时只能导出文件：

```text
导出 CSV / JSON / 后续 PDX
  -> 把文件路径传给 -SourceFile
  -> AI Gateway 只读分析
```

## 5. 当前边界

- 只读分析，不修改测试配置。
- 不控制测试设备。
- 不写客户数据库。
- 模型 API Key 由客户环境变量配置，不放进脚本。
- PDX 先等真实样例或官方工具确认后再接 Adapter。

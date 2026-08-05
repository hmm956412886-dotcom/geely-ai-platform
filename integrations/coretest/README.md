# CoreTest Agent 集成

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\integrations\coretest\install.ps1
```

脚本把 Qt 连接器复制到客户仓库，并对 `MainWindow` 增加最小入口。启动 CoreTest 后右侧自动出现 Agent；
多套模型 API 和模型可从底部“API”入口添加、测试、切换和删除。OpenCode Runtime 由 Connector 自动管理，无需用户配置
命令或单独启动，随后可读取已注册用户工程、分析附件和当前对象，并在该工程中自动写入和运行 pytest 测试；CoreTest 和 Agent 产品源码不会暴露为可写工作区。
Connector 同时自动启动本机只读能力桥，OpenCode 可通过内置 `coretest-host` 命令主动查询工程、文件、DBC、Trace 和诊断缓存，不需要模拟界面点击。桥地址和随机令牌不会进入 WebView。
PDX 分析复用 `odxtools==11.4.1`；CoreTest 构建环境必须安装该依赖。

连接器只读取项目、Trace、DBC 和诊断日志，不包含 CAN 发送、回放启动、UDS 执行或刷写入口。

生成包含独立 AI Gateway Sidecar 的 CoreTest 交付 ZIP：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build-coretest-delivery.ps1
```

交付机解压后直接启动 CoreTest，并在右侧 Agent 底部配置模型 API。普通用户不需要复制 `.env`、启动终端或单独运行 OpenCode。

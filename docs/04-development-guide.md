# 开发与验收指南

## 原则

- 每项开发必须对应 `docs/13-reusable-ai-plugin-development-plan.md` 的可验收产品能力。
- 优先复用 CoreTest 服务、Python/Qt 标准能力和已固定的开源依赖。
- 不为单个实现增加接口、工厂、框架或未来配置。
- Gateway REST API 是宿主集成协议；宿主不能依赖 Gateway 内部 Python 模块。
- 所有汽车数据工具默认只读，写操作和设备控制不进入 Tool Registry。生成代码只能由用户明确保存到当前项目的 `generated_tests`，且不得自动执行。
- 客户源码、PDX、DBC、BLF、日志、数据库和密钥不得提交到本仓库。

## 目录职责

```text
frontend/copilot-shell/     可嵌入 Copilot UI
src/ai-gateway/             REST Gateway、分析、知识和 Agent 编排
integrations/coretest/      CoreTest Qt Host Connector 和安装集成
samples/host-integration/   与具体宿主无关的 REST SDK 样例
contracts/                  OpenAPI、Manifest 和 Tool Registry
scripts/                    启动和部署检查
```

## 改动顺序

1. 在主计划中确认范围和验收标准。
2. 读取真实调用链和现有测试。
3. 为新增契约或错误先写最小测试。
4. 实现最少代码并运行相关测试。
5. 运行全量 Gateway、前端、Connector 和部署检查。
6. 检查 Git diff、CodeGraph、密钥和客户数据后再提交。

## API 要求

- JSON 请求拒绝未知字段、无效类型和超限数据。
- 成功和失败均返回 `request_id`。
- 会话数据按 `host_session_id` 隔离并有数量/大小上限。
- 浏览器只持有 Access Token；本地文件注册和 Host Snapshot 写入使用 Host Token。
- OpenAPI、Plugin Manifest、Tool Registry 与实现同步测试。

## 验证命令

完整命令以主计划“固定验证”为准。桌面集成额外执行：

```powershell
cd D:\geely-ai-platform
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-ai-gateway.ps1
git status --short
git diff --check
```

涉及 Qt UI、WebView 或打包的改动必须实际启动 CoreTest 并截图检查。纯单元测试不能替代桌面验收。

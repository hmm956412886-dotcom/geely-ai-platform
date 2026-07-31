# OpenCode 开源合规

## 固定版本

客户版本只使用 `config/open-source-lock.json` 锁定的 OpenCode：

```text
Repository: https://github.com/anomalyco/opencode.git
Tag: v1.18.10
Commit: 7902e04c3a67f7c69726bc955efb46e29214c797
License: MIT
```

OpenCode 的 MIT License 允许商业使用、修改和再分发，不要求 Geely AI Platform 或客户业务代码开源。
再分发时必须保留 OpenCode 的版权声明和 MIT 许可全文。

## 交付规则

- OpenCode 保持独立 Sidecar，不复制其源码到本项目，也不维护 Fork。
- 开发和客户运行时可以使用锁定版本的官方 Windows CLI；必须校验版本、下载来源和 SHA-256。
- 如以后必须修改 OpenCode，再切换到固定 Commit 的源码构建，并保存补丁和修改说明。
- 客户包必须包含 OpenCode MIT License、第三方许可证/Notices 和依赖 SBOM。
- 出现 GPL、AGPL、SSPL、BUSL、自定义或未知许可证时必须人工审查；未批准不得交付。
- 禁止使用 `latest`、滚动安装脚本或来源不明的 `opencode.exe`。

## 当前状态

- 已锁定 OpenCode `v1.18.10`、Commit 和根 MIT License。
- Gateway 工作区和 Runtime 生命周期骨架已经实现。
- OpenCode 尚未进入客户 ZIP；当前交付脚本会明确排除它。
- 第三方 Notices/SBOM 尚未生成，因此当前只允许开发联调，不允许正式交付 Agent Runtime。

这份合规门禁不阻塞 Agent 功能开发；在把 OpenCode 加入客户 ZIP 前完成即可。

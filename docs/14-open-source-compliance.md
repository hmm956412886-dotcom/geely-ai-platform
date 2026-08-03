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
- 已锁定官方 ZIP 和解压后 `opencode.exe` 的大小与 SHA-256。
- 已按固定 Commit 的 `packages/opencode` 生产依赖闭包生成 CycloneDX 1.6 SBOM，并保留 npm 元数据缺失项的许可证证据。
- 已生成 OpenCode MIT License 和第三方 Notices；自动门禁拒绝 `UNKNOWN`、GPL、AGPL、SSPL 和 BUSL。
- 极狐完整 CoreTest 仓库使用 Git LFS 携带校验后的官方 EXE；客户运行时不联网下载 Runtime。
- Gateway 工作区、Runtime 生命周期和 CoreTest 后台自动启动已经实现。

SBOM 与 Notices 是工程交付门禁，不替代客户或法务部门的最终许可证审批。OpenCode 版本升级时必须重新生成并审查全部材料。

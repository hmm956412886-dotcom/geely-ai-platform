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

- OpenCode Runtime 保持独立 Sidecar，继续使用未修改的锁定版官方 Windows CLI；必须校验版本、下载来源和 SHA-256。
- CoreTest Agent 前端允许基于同一锁定 Commit 的 OpenCode Web UI 源码构建，但必须使用可审计补丁或明确的 CoreTest 发行分支，不跟随上游滚动版本。
- UI 源码包、上游 Commit、应用补丁顺序、构建命令、构建工具版本和最终静态资源 SHA-256 必须可重复追溯。
- 修改后的 UI 及其依赖必须重新生成前端 SBOM、第三方 Notices 和许可证清单；不能直接沿用 Runtime 的依赖审计结果。
- OpenCode 原始版权和 MIT License 必须随修改后的 UI 一同交付，修改说明中必须区分上游代码与 CoreTest 定制。
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
- OpenCode 原生 Web UI 已通过 Gateway 同源 HTTP/SSE 安全代理完成验证，Runtime 密码不进入 WebView；开发分支已将它设为 CoreTest 默认入口，旧 assistant-ui 作为回退。
- 已从锁定 Commit 逐文件校验并归档 UI workspace：`packages/app` 593 个文件，`packages/core`、`schema`、`session-ui` 678 个文件，`packages/sdk`、`client` 69 个文件；三个源码归档及 SHA-256 记录在 `third_party/OpenCode-UI-SOURCE.json`。
- `scripts/build-opencode-ui.ps1` 已从上述归档构建 CoreTest Profile；生产依赖由带 SHA-256 的 `pnpm-lock.yaml` 固定，并记录已验证的 Node `24.14.0`、pnpm `11.9.0`。当前构建输出 `frontend/opencode-coretest/dist` 的 864 个静态文件。Gateway、PyInstaller 和 CoreTest 安装脚本均优先携带该源码构建结果，Runtime 内置 UI 只作开发回退。
- 已按实际生产依赖树生成 UI CycloneDX 1.6 SBOM 和第三方 Notices：99 个组件，无 `UNKNOWN`、GPL、AGPL、SSPL 或 BUSL；100 个依赖节点无重复、缺失或悬空引用。
- 已生成并逐项复核 864 个 UI 静态资源 SHA-256。`scripts/build-coretest-delivery.ps1` 会在打包前重建 UI、重生成合规材料并执行版本、格式和资产门禁。
- 工程合规门禁已经具备；正式客户交付仍需客户或法务最终许可证审批，并在干净 Windows 环境完成交付 ZIP 验收。

原生 UI 作为默认入口时，`scripts/build-coretest-delivery.ps1` 必须找到并校验以下材料，否则在编译前直接失败：

```text
third_party/OpenCode-UI-SOURCE.json
third_party/OpenCode-UI-SBOM.cdx.json
third_party/OpenCode-UI-THIRD-PARTY-NOTICES.txt
third_party/OpenCode-UI-ASSETS.sha256
```

SBOM 与 Notices 是工程交付门禁，不替代客户或法务部门的最终许可证审批。OpenCode 版本升级时必须重新生成并审查全部材料。

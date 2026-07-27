# CodeGraph 使用说明

## 1. 当前状态

项目已接入 `@colbymchenry/codegraph`，并在项目根目录生成本地索引：

```text
.codegraph/
```

当前项目还主要是 Markdown、JSON Schema 和 Docker 配置，业务代码很少，所以 CodeGraph 的节点和边数量暂时很少。等后续 C# AI Gateway 和 Python Feishu Sync Worker 开始实现后，CodeGraph 的价值会明显上来。

## 2. 为什么接入 CodeGraph

CodeGraph 用来帮助 AI 和开发者理解代码结构：

- 查看项目文件结构。
- 搜索函数、类、方法和符号。
- 分析调用方和被调用方。
- 判断修改某个函数会影响哪些代码。
- 后续可通过 MCP 接入 Codex、Claude Code、Cursor 等 Agent。

白话理解：它相当于给 AI 装一个“项目地图”，避免 AI 只靠全文搜索和猜测理解代码。

## 3. 本机运行方式

当前机器没有全局 `node` 和 `codegraph` 命令，所以使用 Codex 捆绑的 Node 启动 CodeGraph。

在 PowerShell 中进入项目目录：

```powershell
cd D:\geely-ai-platform
```

查看帮助：

```powershell
& 'C:\Users\humin\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' 'C:\Users\humin\.pnpm-store\v11\links\@colbymchenry\codegraph\1.5.0\ce80a709c46f69a655419c50bba53ca1f3c87fefd1ed82b33461b4cc74d6ae61\node_modules\@colbymchenry\codegraph\npm-shim.js' --help
```

重建索引：

```powershell
& 'C:\Users\humin\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' 'C:\Users\humin\.pnpm-store\v11\links\@colbymchenry\codegraph\1.5.0\ce80a709c46f69a655419c50bba53ca1f3c87fefd1ed82b33461b4cc74d6ae61\node_modules\@colbymchenry\codegraph\npm-shim.js' index
```

增量同步：

```powershell
& 'C:\Users\humin\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' 'C:\Users\humin\.pnpm-store\v11\links\@colbymchenry\codegraph\1.5.0\ce80a709c46f69a655419c50bba53ca1f3c87fefd1ed82b33461b4cc74d6ae61\node_modules\@colbymchenry\codegraph\npm-shim.js' sync
```

查看索引状态：

```powershell
& 'C:\Users\humin\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' 'C:\Users\humin\.pnpm-store\v11\links\@colbymchenry\codegraph\1.5.0\ce80a709c46f69a655419c50bba53ca1f3c87fefd1ed82b33461b4cc74d6ae61\node_modules\@colbymchenry\codegraph\npm-shim.js' status
```

查看文件结构：

```powershell
& 'C:\Users\humin\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' 'C:\Users\humin\.pnpm-store\v11\links\@colbymchenry\codegraph\1.5.0\ce80a709c46f69a655419c50bba53ca1f3c87fefd1ed82b33461b4cc74d6ae61\node_modules\@colbymchenry\codegraph\npm-shim.js' files
```

搜索符号：

```powershell
& 'C:\Users\humin\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' 'C:\Users\humin\.pnpm-store\v11\links\@colbymchenry\codegraph\1.5.0\ce80a709c46f69a655419c50bba53ca1f3c87fefd1ed82b33461b4cc74d6ae61\node_modules\@colbymchenry\codegraph\npm-shim.js' query KnowledgePlugin
```

## 4. 建议使用习惯

每次新增或修改较多代码后，执行：

```powershell
& 'C:\Users\humin\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' 'C:\Users\humin\.pnpm-store\v11\links\@colbymchenry\codegraph\1.5.0\ce80a709c46f69a655419c50bba53ca1f3c87fefd1ed82b33461b4cc74d6ae61\node_modules\@colbymchenry\codegraph\npm-shim.js' sync
```

如果索引异常，执行：

```powershell
& 'C:\Users\humin\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' 'C:\Users\humin\.pnpm-store\v11\links\@colbymchenry\codegraph\1.5.0\ce80a709c46f69a655419c50bba53ca1f3c87fefd1ed82b33461b4cc74d6ae61\node_modules\@colbymchenry\codegraph\npm-shim.js' index
```

## 5. MCP 接入

CodeGraph 支持通过 `install` 命令接入 Codex CLI、Claude Code、Cursor 等 Agent。

本项目暂时只完成项目本地初始化，不主动修改全局 Agent 配置。等项目代码开始增长后，再决定是否执行 MCP 安装。

如果要接入，再单独评估：

```powershell
codegraph install
```

该命令可能修改用户级 Agent 配置，执行前需要明确确认目标 Agent 和配置位置。


# GitHub 版本控制指南

## 1. 目标

GitHub 只保存代码、配置模板、文档和可公开的脱敏测试样例。

不要提交：

- 客户真实测试数据。
- PDX、MF4、MDF、BLF、DBC 等原始测试文件。
- API Key、Token、飞书凭据。
- 客户软件安装包。
- 本地 `.codegraph/` 索引数据库。

## 2. 推荐仓库策略

```text
main        稳定版本，只合并通过测试的代码
develop     日常集成分支
feature/*   单个功能开发
bugfix/*    缺陷修复
release/*   发布准备
```

MVP 阶段也可以简化：

```text
main
feature/*
```

如果只有一两个人开发，先用简化策略，不要上来就把流程做重。

## 3. 推荐提交方式

提交信息用 Conventional Commits：

```text
feat(feishu): add cli provider
feat(test-data): add pdx file adapter contract
docs(mvp): update no-source integration plan
test(provider): cover lark-cli failures
chore(git): add data artifact ignores
```

## 4. 第一次推到 GitHub

在项目目录执行：

```powershell
cd D:\geely-ai-platform
git init
git add .
git commit -m "feat: scaffold geely ai platform"
git branch -M main
git remote add origin https://github.com/<org>/<repo>.git
git push -u origin main
```

如果已经有远程仓库：

```powershell
git remote add origin https://github.com/<org>/<repo>.git
git push -u origin main
```

## 5. 版本号怎么打

建议使用语义化版本：

```text
v0.1.0  MVP：飞书 CLI + 测试数据文件分析 + 可配置模型 API
v0.2.0  接入客户真实 API 或文件解析器
v0.3.0  AI Gateway + SK Plugin 完整闭环
v1.0.0  可交付客户的稳定版本
```

打 tag：

```powershell
git tag -a v0.1.0 -m "MVP baseline"
git push origin v0.1.0
```

在 GitHub 上为 tag 创建 Release，Release Notes 写：

- 新增能力。
- 修复问题。
- 配置变更。
- 已知限制。
- 升级步骤。

## 6. 大文件怎么处理

真实客户数据不要进 GitHub。

如果确实需要少量脱敏 PDX 或二进制样例：

1. 先确认已脱敏。
2. 文件尽量小。
3. 使用 Git LFS。
4. 明确写入 `tests/fixtures/README.md` 说明来源和脱敏方式。

Git LFS 示例：

```powershell
git lfs install
git lfs track "*.pdx"
git add .gitattributes
```

默认项目已在 `.gitignore` 中忽略常见测试数据文件，防止误提交。

## 7. PR 合并前检查

至少执行：

```powershell
cd D:\geely-ai-platform\workers\feishu-sync
$env:PYTHONPATH='src'
python -m unittest discover -s tests -p "test_*.py"
```

以及：

```powershell
cd D:\geely-ai-platform\infra\postgres
python -m unittest discover -s tests -p "test_*.py"
```

如果修改了 CodeGraph 支持的代码，执行：

```powershell
codegraph sync
```

当前机器如果没有全局 `codegraph`，参考 `docs/05-codegraph-usage.md`。

## 8. 推荐 GitHub 保护规则

仓库稳定后再开启：

- `main` 分支禁止直接 push。
- PR 至少 1 人 review。
- 测试通过后才能合并。
- 禁止提交 secret。
- Release 只从 tag 创建。

MVP 早期不需要流程过重，但至少要保证 `main` 随时能跑。


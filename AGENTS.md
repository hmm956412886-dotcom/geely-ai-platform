# AGENTS.md

本文件约束本项目内的 AI 编码行为。目标是先做出可展示、可集成的产品 MVP，再逐步补真实能力。

## 1. 先想清楚再写代码

- 不要假设客户软件内部实现；没有源码时，以 HTTP、WebView、CLI、文件契约为准。
- 有多种理解时，先说清楚取舍。
- 不清楚 PDX 等测试文件格式时，不猜格式；优先找官方工具、SDK、CLI 或客户导出能力。
- 每个任务先定义可验收结果。

## 2. 简单优先

- 能用标准库，就用标准库。
- 有成熟开源项目或官方 SDK，就优先复用，不从 0 自研。
- 不为单次使用写抽象。
- 不提前做动态 UI、多 Agent、向量库迁移、复杂中间件。
- MVP 只保留能展示、能集成、能验证的代码。

## 3. 改动要克制

- 只改和当前任务直接相关的文件。
- 不顺手重构无关代码。
- 不提交客户真实数据、PDX、日志、密钥或本地缓存。
- `.codegraph/`、`__pycache__/`、测试大文件不进入 Git。

## 4. 产品 MVP 优先级

P0 只做：

- AI Gateway 可启动。
- `/demo` 可嵌入展示。
- `/plugin-manifest.json` 描述插件/宿主集成方式。
- `/openapi.json` 描述 HTTP 接口。
- `/api/v1/analyze` 返回只读分析结果。
- 飞书知识库通过 CLI 查询。
- 测试数据通过文件 Adapter 或 fixture 进入。

暂不做：

- 写入客户系统。
- 修改测试配置。
- 控制测试设备。
- 全量迁移飞书知识库。
- 没有真实需求的复杂插件 SDK。

## 5. 验证

每个非平凡改动至少运行对应测试。

常用命令：

```powershell
cd D:\geely-ai-platform\src\ai-gateway
$env:PYTHONPATH='src'
python -m unittest discover -s tests -p "test_*.py"
```

```powershell
cd D:\geely-ai-platform\workers\feishu-sync
$env:PYTHONPATH='src'
python -m unittest discover -s tests -p "test_*.py"
```

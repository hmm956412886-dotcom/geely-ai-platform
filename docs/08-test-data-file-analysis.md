# 测试数据文件分析方案

## 1. 目标

MVP 的数据分析重点是客户测试软件里的测试数据和结果产物，例如 PDX 文件、日志文件、导出的 CSV/Excel/XML/JSON 报告等。

第一阶段不直接连客户数据库，也不要求拿到客户软件源码。

```text
测试软件导出文件 / PDX / 报告
  -> TestDataFileAdapter
  -> 标准 TestRunSummary / CompareResult
  -> TestDataPlugin
  -> SK / AI Gateway
  -> 数据分析结论
```

## 2. 核心原则

1. 先解析文件和导出结果，不碰客户软件内部源码。
2. 优先复用现有解析库、官方 SDK、命令行工具或客户导出工具。
3. 不把客户原始 PDX 文件提交到 GitHub。
4. AI 只解释结构化结果，不直接读取大文件全文。
5. 解析器输出必须可追溯到原始文件名、测试运行 ID、时间戳和指标来源。

## 3. PDX 文件处理策略

PDX 可能是某类测试工程包、诊断数据包或厂商私有格式。没有样例和格式说明前，不猜格式。

建议顺序：

| 优先级 | 做法 | 说明 |
| --- | --- | --- |
| P0 | 找官方解析工具或 CLI | 最稳，避免自己猜二进制格式 |
| P0 | 让客户软件导出 JSON/CSV/Excel | MVP 最快验证数据分析 |
| P1 | 调研 PDX 是否为 ZIP/XML 容器 | 如果是开放容器，可以解析元数据 |
| P1 | 接入客户 SDK | 如果客户提供 SDK，写 Adapter |
| P2 | 自研解析器 | 只有格式明确且无现成工具时才做 |

白话解释：PDX 不要先上来硬拆。先问“有没有官方导出/解析工具”，因为测试数据格式一旦猜错，AI 后面的分析都是错的。

## 4. 标准输出模型

契约文件：

- `contracts/test-run-summary.schema.json`
- `contracts/test-run-compare.schema.json`

`TestRunSummary`：

```json
{
  "run_id": "RUN_001",
  "source_file": "sample.pdx",
  "project_id": "GEELY_TEST",
  "status": "failed",
  "started_at": "2026-07-24T08:00:00Z",
  "finished_at": "2026-07-24T10:00:00Z",
  "total_cases": 120,
  "passed_cases": 108,
  "failed_cases": 12,
  "metrics": {
    "pass_rate": 0.9
  },
  "failures": [
    {
      "case_id": "TC_001",
      "name": "动力响应测试",
      "reason": "扭矩误差超过阈值"
    }
  ]
}
```

`CompareResult`：

```json
{
  "baseline_run_id": "RUN_A",
  "target_run_id": "RUN_B",
  "summary": "目标版本失败用例增加 3 个。",
  "changed_metrics": [
    {
      "name": "pass_rate",
      "baseline": 0.95,
      "target": 0.9,
      "delta": -0.05
    }
  ]
}
```

## 5. MVP 任务

| 编号 | 任务 | 完成标准 |
| --- | --- | --- |
| TD-001 | 建 `TestDataFileAdapter` 接口 | 能接收文件路径并输出标准模型 |
| TD-002 | 支持 JSON fixture | 不依赖真实 PDX 也能跑通分析 |
| TD-003 | 支持 CSV/Excel 导出 | 覆盖最常见客户导出形式 |
| TD-004 | 调研 PDX 工具链 | 找到官方工具、SDK 或样例格式 |
| TD-005 | 建 PDX Adapter | 只有格式明确后再实现 |

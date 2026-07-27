# Feishu Sync Worker

这里放 Python 飞书知识同步 Worker，负责：

1. 通过飞书 CLI 读取知识库内容。
2. 解析 Wiki 节点背后的底层对象类型和 token。
3. 读取 Docx、Sheet、Base 或附件。
4. 转换为 `contracts/document.schema.json` 定义的统一文档格式。
5. 为后续 RAG 保留可替换的 Provider 接口。
6. 可选地将文档元数据、ACL 和索引任务写入 PostgreSQL。

## 第一版只支持

- Wiki 节点。
- Docx 文档。
- 文档标题、章节、正文、来源链接、更新时间。
- 基础 ACL 元数据。

## 暂不支持

- 图片 OCR。
- 大型 Sheet 全量分析。
- Base 全量同步。
- 评论自动入库。
- 直接把文档内容发送给 LLM。

## 推荐复用

- 飞书开放平台官方 API / SDK。
- LangChain 社区的 LarkSuite Loader 作为文档读取参考。
- 标准 JSON Schema 做跨服务契约。

## 当前已实现

`src/feishu_sync/normalize.py` 已实现第一条纯逻辑闭环：

```text
已获取的 Feishu snapshot
  -> 标准 source_type
  -> 标准 sections / heading_path
  -> 稳定 content_hash
  -> ACL 规范化
  -> NormalizedKnowledgeDocument
```

运行测试：

```powershell
$env:PYTHONPATH='src'
python -m unittest discover -s tests -p "test_*.py"
```

当前测试使用本地 fixture，不需要飞书凭据。真实 API Connector 只负责把飞书响应转换成 snapshot，再调用 `normalize_snapshot`。

## 下一段已实现

`src/feishu_sync/repository.py` 已实现可选的落库边界：

```text
NormalizedKnowledgeDocument
  -> upsert source_documents
  -> replace knowledge_sections
  -> replace source_acl_entries
  -> create pending index sync_jobs
```

当前 repository 只依赖 DB-API 风格连接对象，不绑定具体驱动。PostgreSQL 依赖是可选项：

```powershell
pip install -e ".[postgres]"
```

第一阶段主路径不要求安装 PostgreSQL。

## 飞书 CLI Provider

`src/feishu_sync/provider.py` 提供 `FeishuCliProvider`：

```python
from feishu_sync.provider import FeishuCliProvider

provider = FeishuCliProvider()
hits = provider.search("动力系统测试规范")
document = provider.fetch(hits[0].document_ref)
```

默认调用：

```text
lark-cli drive +search --query <query> --format json --as user
lark-cli docs +fetch --doc <document> --format json --as user
```

可以通过 `LARK_CLI_COMMAND` 替换 CLI 可执行文件路径。

当前 Provider 是第一阶段的主知识源。后续新增 `IndexedRagProvider` 时，只需要实现同一组 `search/fetch` 能力，不修改上层编排。

直接通过 Worker CLI 交互：

```powershell
$env:PYTHONPATH='src'
python -m feishu_sync.cli search-feishu --query '动力系统测试规范' --limit 5
python -m feishu_sync.cli fetch-feishu --doc 'doxcn-001'
```

这两个命令会把飞书 CLI 的结果转换成稳定的 JSON，供后续 SK Gateway 调用。

## 本地 ingestion 命令

`src/feishu_sync/cli.py` 提供了一个最小命令，用于验证 snapshot 到标准文档 JSON 的链路：

```powershell
$env:PYTHONPATH='src'
python -m feishu_sync.cli ingest-snapshot --input tests/fixtures/docx_snapshot.json --dry-run
```

输出到文件：

```powershell
$env:PYTHONPATH='src'
python -m feishu_sync.cli ingest-snapshot --input tests/fixtures/docx_snapshot.json --output normalized.json --dry-run
```

写入 PostgreSQL：

```powershell
$env:PYTHONPATH='src'
$env:DATABASE_URL='postgresql://geely_ai:geely_ai_local_only@localhost:5432/geely_ai'
python -m feishu_sync.cli ingest-snapshot --input tests/fixtures/docx_snapshot.json
```

也可以显式传入连接串：

```powershell
$env:PYTHONPATH='src'
python -m feishu_sync.cli ingest-snapshot --input tests/fixtures/docx_snapshot.json --database-url 'postgresql://geely_ai:geely_ai_local_only@localhost:5432/geely_ai'
```

真实写库前需要先执行 `infra/postgres/migrations/001_init_knowledge_sync.sql`。

## 环境变量草案

```text
FEISHU_APP_ID=
FEISHU_APP_SECRET=
FEISHU_SPACE_ID=
FEISHU_ROOT_NODE_TOKEN=
DATABASE_URL=
REDIS_URL=
OBJECT_STORAGE_ENDPOINT=
```

密钥只放在本地 `.env` 或密钥管理系统，不提交到 Git。

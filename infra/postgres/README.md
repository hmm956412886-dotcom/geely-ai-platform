# PostgreSQL Metadata

这里保存知识同步和索引所需的元数据。

## 当前迁移

| 文件 | 说明 |
| --- | --- |
| `migrations/001_init_knowledge_sync.sql` | P0-002：飞书知识同步、章节、ACL、同步任务表 |

## 表职责

| 表 | 职责 |
| --- | --- |
| `source_documents` | 记录飞书文档或附件的来源、版本、同步状态 |
| `knowledge_sections` | 记录标准化后的文档片段，后续关联向量库 |
| `source_acl_entries` | 记录文档访问权限，检索前做 ACL 过滤 |
| `sync_jobs` | 记录同步、删除、索引等后台任务 |

## 第一阶段边界

当前不创建：

- 用户表。
- 项目表。
- 向量表。
- 全文搜索表。
- Prompt 或模型配置表。

原因：这些表还没有真实调用方。先把飞书同步闭环跑通，再根据 Retrieval Service 和 AI Gateway 的实际需要补。

## 本地应用迁移

启动本地 PostgreSQL：

```powershell
docker compose -f infra/docker-compose.yml up -d postgres
```

执行迁移：

```powershell
docker exec -i geely-ai-postgres psql -U geely_ai -d geely_ai -f /migrations/001_init_knowledge_sync.sql
```

上面的命令需要先把 `infra/postgres/migrations` 挂载到容器中。当前 compose 还没有挂载迁移目录，开发早期也可以用数据库客户端手动执行 SQL。

## 状态说明

`source_documents.sync_status`：

| 状态 | 说明 |
| --- | --- |
| `discovered` | 已发现来源，但还没拉取 |
| `fetching` | 正在读取飞书内容 |
| `normalized` | 已转换为标准文档结构 |
| `indexing` | 正在写入索引 |
| `active` | 可被检索 |
| `permission_denied` | 当前身份无权读取 |
| `fetch_failed` | 飞书读取失败 |
| `parse_failed` | 文档解析失败 |
| `index_failed` | 索引写入失败 |
| `deleted` | 来源已删除或不再纳入 |

`sync_jobs.status`：

| 状态 | 说明 |
| --- | --- |
| `pending` | 等待执行 |
| `running` | 正在执行 |
| `success` | 已成功 |
| `failed` | 已失败，保留错误信息 |


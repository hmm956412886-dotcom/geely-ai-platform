# 飞书知识库 Connector 设计

## 1. 目标

把飞书知识库内容转换成与来源无关的标准文档模型，供后续任何 RAG 引擎使用。

```text
Feishu Document
  -> NormalizedKnowledgeDocument
  -> Chunk
  -> Embedding
```

第一阶段不强制迁移数据库，优先通过 `FeishuCliProvider` 直接读取飞书。数据库和向量索引作为后续可替换 Provider。

```text
KnowledgeProvider
  -> FeishuCliProvider      当前阶段，实时调用 lark-cli
  -> IndexedRagProvider     后续阶段，向量库和混合检索
```

## 2. 第一版范围

必须支持：

- Wiki Space。
- Wiki Node。
- Docx 文档。
- 标题层级。
- 正文。
- 来源 URL。
- 更新时间。
- 内容 hash。
- 基础 ACL。

第二版再支持：

- Sheet。
- Base。
- PDF、Word、PPT 附件。
- 图片 OCR。
- 增量事件订阅。

## 3. Wiki token 处理

不要把 `/wiki/<token>` 直接当成文档正文 token。

正确流程：

```text
Wiki URL / wiki token
  -> 获取 Space / Node 信息
  -> 解析底层 obj_type
  -> 解析 obj_token
  -> 按 docx / sheet / bitable / file 选择读取接口
```

需要保存：

- `space_id`
- `node_token`
- `obj_type`
- `obj_token`
- `source_url`
- `parent_node_token`
- `title`

## 4. 当前 CLI 交互流程

```text
用户问题
  -> drive +search
  -> 取得 document_ref
  -> docs +fetch
  -> 标准化为 NormalizedKnowledgeDocument
  -> 返回正文、章节和飞书来源
```

CLI 适合第一阶段验证，但不是完整语义 RAG：

- 优点：不迁移数据、内容实时、沿用飞书权限。
- 限制：关键词搜索、进程调用延迟、并发能力和语义召回有限。

## 5. 同步状态机

```text
DISCOVERED
  -> FETCHING
  -> NORMALIZED
  -> INDEXING
  -> ACTIVE
```

异常状态：

```text
PERMISSION_DENIED
FETCH_FAILED
PARSE_FAILED
INDEX_FAILED
DELETED
```

删除文档时，必须同时：

1. 标记元数据为 `DELETED`。
2. 删除或禁用向量记录。
3. 从检索结果中排除。
4. 保留审计记录。

## 6. ACL 策略

检索前过滤，不是回答后过滤。

```text
user_id
  -> Feishu identity mapping
  -> department / group / role
  -> ACL filter
  -> vector search
```

用户没有权限的文档：

- 不参与召回。
- 不进入 Prompt。
- 不出现在引用列表。

## 7. 索引任务

建议使用 Redis 队列或数据库任务表：

| 字段 | 说明 |
| --- | --- |
| `job_id` | 任务 ID |
| `document_id` | 文档 ID |
| `job_type` | full / incremental / delete |
| `status` | pending / running / success / failed |
| `attempts` | 重试次数 |
| `error_code` | 错误码 |
| `created_at` | 创建时间 |
| `finished_at` | 完成时间 |

## 8. 先不要做的事

- 不要在第一阶段同步整个公司所有知识空间。
- 不要一开始处理全部附件格式。
- 不要先做权限全自动推断。
- 不要把飞书评论直接混进主知识库。
- 不要在 Connector 中调用 LLM。

Connector 只负责取数据和标准化，LLM 编排放在 AI Gateway。后续的向量库 Provider 也必须遵守同一接口。

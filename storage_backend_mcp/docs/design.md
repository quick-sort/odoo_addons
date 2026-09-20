# Storage Backend MCP — 系统设计

## 总体形态

MCP 协议没有带外文件通道（resources 是 server→client 只读），文件内容有两种
载体选择：base64 塞进 tool arguments（受 MCP payload 限制、污染审计表），或
**临时 URL**。本设计选后者：

```
agent ──tools/call──▶ storage_get_upload_url(backend, path)
                          │
                          ├─ adapter 有原生签名能力 (S3 presign)
                          │    → 字节直连对象存储，不过 Odoo
                          └─ 没有 (filesystem/sftp/ftp/…)
                               → 铸一次性 capability token
                                 agent: curl -T file /storage_mcp/t/<token>
                                 Odoo controller 流式转写进 backend.open(path, "wb")
```

工具是 **URL broker**，不搬运字节。工具结果附现成 curl 命令。

## 多态维度：URL 生成策略

同一"给我临时上传/下载 URL"的请求，由后端类型决定落点：

- 组件层扩展点：core 提供默认组件（`presign_upload/presign_download → None`，
  语义"无原生签名能力，走中转"）；`storage_backend_s3_mcp` bridge 覆盖为 boto3
  presign。
- `storage.backend` 模型层公共方法 `presign_upload/presign_download`：先过
  `_gzip_physical`（保持 `.gz` 物理后缀映射一致——presign 出的 key 必须和
  `open()` 实际读写的 key 对得上）再 `_forward` 给 adapter。
- 工具侧：presign 返回 dict 则原样返回；返回 `None` 则铸 token 走中转。
  **加新 bridge 时 core 零改动。**

分层与 `llm_store`+adapter、`llm_knowledge`+extractor、`infohub`+channel 同构。

## 组件继承（不改 vendored OCA 代码）

`base.storage.adapter` 与 `s3.adapter` 都是 vendored 代码。扩展用**组件继承**
（`_inherit = "base.storage.adapter"` 跨 addon 生效），不碰原文件。

## 数据模型

### `storage.mcp.token` — 中转 capability

| 字段 | 说明 |
|---|---|
| `token_hash` | sha256；明文 token `secrets.token_urlsafe(32)` 只出现在 URL，不落库 |
| `backend_id` / `relative_path` | 创建时校验；controller 永不从请求收路径 |
| `mode` | upload / download |
| `expires_at` | 默认 10 分钟，上限 1 小时 |
| `max_size_bytes` | 上传硬上限 |
| `uses_used` | 上传 token 单次使用 |
| `create_uid` | 哪个 MCP 用户的 tool call 铸的（审计链） |

下载 token 可多次读（TTL 内）。`ir.cron` 清理过期行。

### `storage.upload` — 暂存注册表（跨工具货币）

| 字段 | 说明 |
|---|---|
| `name` | 原始文件名 |
| `backend_id` / `relative_path` | `.mcp_staging/<uuid>/<filename>`，agent 永不发明路径 |
| `sha256` / `size_bytes` | commit 时确定 |
| `state` | pending → staged → consumed / expired |
| `expires_at` | staged 后默认 24h |
| `create_uid` | 上传者 |
| `consumed_model` / `consumed_res_id` | 谁取走的（审计闭环） |

staging 前缀是 GC 安全性的来源：cron 可**无条件删除**前缀下对象，
不碰正式数据。

### `storage.backend` `_inherit` 治理字段

- `mcp_read_enabled` / `mcp_write_enabled`（默认 False）：写工具与 URL 签发的
  治理闸门，防止把存敏感数据的后端误暴露给 agent。
- 权限顺其自然：MCP 以 API key 用户身份执行，`storage_backend` ACL 是
  `group_system`，非授权用户走 ORM 自然 AccessError，无需额外代码。

## 上传协议：stage → transfer → commit → consume

```
1. storage_stage_upload(filename="skill.zip")
   → {file_id, upload: {url, method, headers}, curl}
2. agent: curl -T skill.zip '<url>'        (presign 直连，或中转 controller)
3. storage_commit_upload(file_id)
   → {state: staged, sha256, size}
4. skillhub_create_skill(..., file_id=42)   # 下游工具
```

**commit 是协议统一的关键**：presign 路径下字节直连对象存储，Odoo 收不到完成
事件、算不了 hash。统一为"上传完必须 commit"——中转路径 controller 边流边算好
hash，commit 近乎 no-op；presign 路径 commit 时 adapter 流式读对象算 hash
（不进内存）。agent 学到的协议只有一种。

**consume 只接受 staged**：保证消费方永远拿到校验过完整性的对象。
消费方集成契约（暴露给未来所有"基于文件上传的 MCP"）：

```python
upload = self.env["storage.upload"].browse(file_id)
with upload.consume(res_model=..., res_id=...) as stream:
    ...
# with 退出时 state → consumed，staging 对象删除
```

`consume()` 内部：state/expiry/owner 校验、（可选）重算 sha256 防调包、
yield 打开的流。

## 直写 vs 暂存

| | 直写（direct） | 暂存（staged） |
|---|---|---|
| 场景 | 往后端真实路径写产物 | 上传给另一个工具消费的载荷 |
| agent 关心路径 | 关心，路径即结果 | 不关心，物理位置是实现细节 |
| 引用 | `(backend, path)` | `file_id` |
| GC | 无（普通文件） | 未消费自动清理 |

**消费方收 `file_id` 而非路径是安全边界**：收路径则 agent 可把后端上任意
已存在文件（如含凭据的导出）喂给下游解压逻辑；收 `file_id` 则引用范围限定在
"该用户经 audited tool call 上传且未消费"的集合。加 state 机（consumed 不可
重放）+ 过期清理 + `consumed_model` 审计。

## 中转 controller

路由 `auth="none"`, `csrf=False`（token 即凭证，agent 的 curl 拿不到 MCP
API key；capability URL 是唯一现实选择，与 S3 presigned、GitHub upload URL
同构）：

- `PUT /storage_mcp/t/<token>`：`request.httprequest.stream` 分块读 body
  （禁止 `get_data()` 全量进内存），边写 `backend.open(path, "wb")` 边计数，
  超 `max_size` 中止并删半成品；完成返回 `{size, sha256}` 并消耗 token。
- `GET /storage_mcp/t/<token>`：`open(path, "rb")` 流式响应；
  Content-Length 尽力取自 `stat`。

兜底：短 TTL + 上传一次性 + 尺寸上限 + 访问记数。

## 工具面

挂在 abstract model（仿 `llm.tool.builtin.records`），`@llm_tool` 自动注册进
`llm.tool`；MCP 客户端与 Odoo 内部 agent 双端可用。工具名全局唯一
（`execute_mcp_tool` 按 name limit=1 查找），统一 `storage_` 前缀：

| 工具 | hints |
|---|---|
| `storage_list_backends` | read_only |
| `storage_list_files` / `storage_stat_file` | read_only；stat 是 presign 路径的统一验证原语 |
| `storage_read_file` | read_only；小文本直接返回（带截断），免得小文件也走 curl |
| `storage_get_upload_url` / `storage_get_download_url` | 直写场景 |
| `storage_stage_upload` / `storage_commit_upload` | 暂存场景 |
| `storage_delete_file` | destructive |

`backend` 参数用名字而非 id（id 每 db 不同，agent 拿名字才可复用）。
`overwrite` 必须显式 True，否则已存在时报错。

## 边角

- **overwrite × presign**：S3 presign PUT 天生覆盖。v1 签发时查存在性并警告
  （接受竞态 last-write-wins）；讲究可把 `IfNoneMatch: "*"` 纳入签名，refinement。
- **审计**：arguments 只含 path/backend/ttl，无 base64 blob，
  `llm.mcp.tool.call.arguments`（fields.Json）落库无害。
- **S3 无 Odoo 侧尺寸上限**是 presign 固有代价（可日后 bucket policy 收紧）；
  中转路径有硬上限（config param，默认 2GB）。
- 路径安全（`..`/绝对路径/反斜杠拒绝、`directory_path` 根限定、gzip 映射）
  全部复用 `storage.backend` 公共 API，不新写。

## 被否决的方案

| 方案 | 否决理由 |
|---|---|
| base64 进 tool arguments | 大小受限；`llm.mcp.tool.call.arguments` 审计表会被 blob 污染。 |
| 复用 `ir.attachment` 当引用货币 | 字节落 Odoo filestore/db，绕开 `storage.backend`，存储路径分叉两条，presign/中转设计作废。 |
| S3 presign 写进 core | 强拖 boto3/`storage_backend_s3` 进核心依赖，纯 filesystem 部署受害。bridge 拆出后是纯增量。 |
| 消费方收 `(backend, path)` | 引用范围失控（可指后端任意已有文件）、无生命周期、无来源审计。 |
| 分块/断点续传 | agent 日常载荷（文档/zip/图）单次 HTTP 已覆盖；adapter `open` 契约只有 rb/wb，代价不成比例。 |
| 每后端一把长期 API key 给 agent | 凭证泄漏面大且无法吊销；capability token 短 TTL 一次性，风险面小得多。 |

## 明确的扩展点

1. **bridge addon**：`_inherit` 某 adapter 组件，覆盖 `presign_upload/download`。
2. **下游消费方**（skillhub 等）：`storage.upload.consume()` 上下文管理器。

# Storage Backend SharePoint — 开发约束（自动加载）

设计文档见 `docs/`，这是唯一要求来源，改代码前先读：

- `docs/requirements.md` — 业务需求与边界
- `docs/design.md` — 与 microsoft_graph 的分工、路径映射、上传策略
- `docs/acceptance.md` — 验收标准（QC 唯一依据）

红线：

1. **认证一律走 `microsoft.graph.service`**：本模块不自建 OAuth/token 逻辑，
   不新增凭证存储。
2. **请求始终以当前用户身份发出**：后台任务须 `with_user(原用户)`，
   不得以 superuser 身份访问 Graph。
3. **续链/上传 URL 只接受 https**，临时 URL 不落库不打日志。

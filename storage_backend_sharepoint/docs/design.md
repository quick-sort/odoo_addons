# Storage Backend SharePoint — 系统设计

## 定位

`microsoft_graph` 的第一个消费者：auth（应用注册、委托凭证、Graph HTTP
客户端）全部来自核心模块，本模块只做 SharePoint 文档库的 storage 适配，
与 `storage_backend_s3_mcp` 之于 `storage_backend_mcp` 的 bridge 关系同构。

## 组件与模型

单一组件（不变）：

```python
class SharePointStorageAdapter(Component):
    _name = "sharepoint.storage.adapter"
    _inherit = "base.storage.adapter"
    _usage = "sharepoint"          # backend_type → 组件查找约定
```

`storage.backend` 扩展字段：

| 字段 | 说明 |
|---|---|
| `sharepoint_application_id` | m2o `microsoft.graph.application`，ondelete=restrict；提供认证与 scope |
| `sharepoint_drive_id` | 文档库的稳定 Graph drive ID |
| `sharepoint_root_item_id` | 可选根 driveItem（空则用库根；`directory_path` 在其下） |
| `sharepoint_site_id` | 仅展示用途 |
| `sharepoint_read_only` | Odoo 侧写保护 |

凭证不落在本模块：`microsoft.graph.credential` 按（应用, 用户）存，
同应用的所有 backend 共享一次用户授权。

## 与核心的分工

| 关注点 | microsoft_graph | 本模块 |
|---|---|---|
| 应用注册、委托凭证、OAuth 流、token 刷新 | ✓ | |
| Graph HTTP 客户端（401/429/404/403 语义） | ✓ | |
| drive 路径端点、children 分页、上传会话 | | ✓ |
| backend 字段、Read Only、connect 路由 | | ✓ |

## 路径映射

- 逻辑路径经 base adapter 的 `_fullpath`（含 `directory_path`）→
  `_rooted_path` 得到库内相对路径；
- 端点形态：有根 item 时 `drives/{drive}/items/{root}`，否则
  `drives/{drive}/root`；子路径用 `:/path:` 语法；
- 大小写不敏感查找子项（SharePoint 语义），创建目录用
  `conflictBehavior=fail` 防并发重名。

## 上传策略

≤4 MiB 直接 PUT content；更大走 createUploadSession + 10 MiB 顺序分片
（429 退避、`nextExpectedRanges` 续传）。uploadUrl 只接受 https。

## v2.0.0 断裂变更

tenant/client/secret/scope 字段与 `storage.sharepoint.credential` 模型移除
（认证归 `microsoft.graph.application` / `microsoft.graph.credential`）。
无存量数据（用户确认），不写迁移脚本，README Upgrade notes 写明手工
路径。

## 被否决的方案

| 方案 | 否决理由 |
|---|---|
| 保留 backend 上的认证字段，m2o 为可选 | 两处配置真相；凭证到底跟谁走含糊，违反核心的“一个应用一份凭证”模型。 |
| backend 各自持有 scope 字段 | 同应用凭证共享，刷新按应用 scope 签发；backend 级 scope 无法兑现，反成误导。 |
| 迁移脚本自动转换 v1 配置 | 本环境不能跑 docker 验证迁移；存量为零，脚本纯风险。 |
| 走 SharePoint REST v2 而非 Graph | 权限模型与 Graph 委托流不统一，SSO 桥接失效。 |

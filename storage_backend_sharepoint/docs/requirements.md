# Storage Backend SharePoint — 业务需求

## 要解决的问题

Odoo 需要以**每个 Odoo 用户自己的 SharePoint 权限**读写 SharePoint 文档库
（`storage.backend` 体系下）：用户在 SharePoint 里能看到/能改的，在 Odoo 里
同样能；用户没有的权限，Odoo 也不越权。

## 范围

**做**：

- `storage.backend` 新类型 `sharepoint`：绑定一个 Microsoft Graph 应用注册
  （`microsoft_graph`）+ 一个文档库（Graph drive ID）+ 可选根 driveItem；
- 委托认证复用 `microsoft_graph`（不自建 OAuth）；
- 适配 base storage adapter 契约：`open`（读写流式）、`list`（含递归）、
  `exists`/`stat`/`get_size`、`rename`/`move_files`、`delete`/`rmdir`、
  `validate_config`；
- 小文件走 Graph content 端点，大文件走可续传 upload session（分片）；
- backend 级 Read Only 开关（Odoo 侧挡写操作）。

**不做**：

- 不做认证（OAuth/token/Graph 客户端）——全部在 `microsoft_graph`；
- 不动 `ir.attachment`、不依赖 `one_storage`；
- 不做 SharePoint REST/CSOM 兼容面——只用 Graph drive API；
- 不做应用权限（client credentials）访问。

## 非功能要求

1. **权限等价**：Microsoft 侧按用户原生权限鉴权，Odoo 不做提权。
2. **离线可测**：所有 Graph 调用在测试里 mock。
3. **升级断裂已声明**：v1 配置字段移除，README 写明升级路径。

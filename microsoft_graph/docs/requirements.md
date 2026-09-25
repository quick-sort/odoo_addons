# Microsoft Graph — 业务需求

## 要解决的问题

多个 Odoo 集成都要以**当前 Odoo 用户自己的身份**访问 Microsoft Graph
（SharePoint 文档库是第一个，未来可能有 OneDrive、Outlook 邮件、Teams）。
每个消费者各自实现一遍 Entra OAuth 会重复：

- 应用注册配置（tenant/client_id/secret/scope）散落在各消费者模型上；
- 同一个用户要对每个消费者各授权一次；
- token 刷新、401 重试、错误解析等 HTTP 逻辑无法共享。

把 auth 收敛到一个核心模块，消费者只保留业务逻辑。

## 范围

**做**：

- `microsoft.graph.application`：Entra 应用注册（tenant、client_id、secret、
  委托 scope、自服务授权开关），支持 `server_environment` 提供 secret。
- `microsoft.graph.credential`：按（应用, 用户）存储的委托凭证与 OAuth 流程
  状态（PKCE state/verifier、回调后跳转目标）。
- 委托 OAuth v2 授权码流程（PKCE、state 单次有效 10 分钟）、token 刷新
  （`invalid_grant` 报错引导用户重新授权）。
- Microsoft Graph HTTP 客户端 `_request`：401 自动刷新重试、429 按
  `Retry-After` 重试、404→`FileNotFoundError`、403→`AccessError`、
  Graph 错误负载解析、续链 URL 仅限 https+graph.microsoft.com。
- `/microsoft_graph/connect/<id>` 自服务授权路由 +
  `/microsoft_graph/oauth/callback` 回调（唯一需要注册到 Entra 的 redirect URI）。
- `res.users._set_microsoft_graph_tokens` 桥接 hook，供 Entra SSO 登录集成
  复用登录时拿到的 Graph token。

**不做**：

- 不做应用权限（client credentials）流——按设计只用委托权限，Microsoft 侧
  始终按用户原生权限鉴权。
- 不做任何具体 Graph 资源访问（drive、mail 等）——归消费者 addon。
- 不做 token 的额外加密存储（与 Odoo 内置 Microsoft 凭证同一安全模型）。
- 不做多公司隔离（应用注册按实例共享）。

## 非功能要求

1. **纯底座**：不装任何消费者时，本模块只是配置与授权 UI，无副作用。
2. **离线可测**：所有网络调用（token 端点、Graph）在测试里全 mock。
3. **向后无包袱**：无存量数据迁移义务（用户确认无存量）。

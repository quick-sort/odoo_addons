# InfoHub Email Channel — 开发约束（自动加载）

设计文档见 `docs/`，改代码前先读：

- `docs/requirements.md` — 业务需求与边界
- `docs/design.md` — 中转模型、alias 路由、被否决方案
- `docs/acceptance.md` — 验收标准（QC 唯一依据）

红线：

1. **`infohub.item` 不得继承 `mail.thread`**——邮件走 `infohub.email.message`
   中转，池子不带 chatter。
2. **一个静态 alias 收所有邮件**，归属靠 `channel.email_to` 匹配，禁止为每个
   newsletter 加 alias。
3. 本 addon 只贡献 `email` 一个渠道类型，配置字段加在自己 `_inherit` 上。

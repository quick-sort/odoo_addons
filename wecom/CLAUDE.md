# wecom — 开发约束（自动加载）

设计文档见 `docs/`，这是唯一要求来源，改代码前先读：

- `docs/requirements.md` — 业务需求与边界
- `docs/design.md` — 架构、模型、撤回链路、被否决的方案
- `docs/acceptance.md` — 验收标准（QC 唯一依据）

红线（来自 design.md，勿违背）：

1. 其他模块发消息只能走 `wecom.app.send_message()`；`_send_message()/_send_articles()/_recall_message()` 是内部接口，禁止外部直调。
2. 所有企业微信调用必须经 `get_wecom_client()`（token 缓存）；撤回用 `client.post('message/recall', ...)`（wechatpy 无该封装，勿另起 requests）。
3. 撤回失败簿记走独立 cursor（`_write_recall_failure`）：UserError 回滚会吞掉当前事务的写入。
4. 测试对 wechatpy 全 mock，禁止联网。

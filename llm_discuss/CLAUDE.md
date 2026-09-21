# llm_discuss — 开发约束（自动加载）

设计文档见 `docs/`，这是唯一要求来源，改代码前先读：

- `docs/requirements.md` — 业务需求与边界
- `docs/design.md` — 架构、模型、扩展点、被否决的方案
- `docs/acceptance.md` — 验收标准（QC 唯一依据）

红线（来自 design.md，勿违背）：

1. **回复人格 ≠ 执行身份**：隐藏 `llm.thread`、记录读取、工具执行一律以
   `source_user`（或 Live Chat 的低权限 bot）身份；provider 凭据与最终发帖用窄
   sudo，绝不把 sudo recordset 传给工具。
2. **附件读取不越权**：附件 `datas` 在 execution user 身份下读，读不到（尤其
   Live Chat 访客附件）时 fail closed，禁止升级 sudo 或切换执行主体。
3. **附件透传只走 `_invoke_with_background`**，公开 `invoke()` 不接受
   `attachment_ids`，也不接受任意执行用户 / system 背景。

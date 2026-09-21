# LLM Discuss — 验收标准

> `llm_discuss` 当前无 `tests/`。附件功能落地时按 `llm` 测试约定新增 `tests/`
> （`@tagged("post_install", "-at_install")`，mock provider adapter）。既有能力
> （触发/接管/栅栏队列/页面上下文）暂无测试，属待补项，见文末。

## 附件（入方向）

### AC-1 图片进入多模态上下文

图片附件经多模态模型进入 provider 请求（mock adapter 断言 content 含 image /
document block）。— `test_image_attachment_forwarded`

### AC-2 文本文件进入上下文

txt / md / csv 等文本附件作为 user content 的一部分（mock adapter 断言 text 含
文件内容）。— `test_text_attachment_forwarded`

### AC-3 非多模态模型 + 图片 → 提示并跳过

`supports_image_input=False` 时图片被剔除，channel 收到「不支持」提示，文本回复
仍生成。— `test_image_skipped_non_multimodal`

### AC-4 视频 / Office / 音频 → 明确提示

不支持的 mimetype 在 channel 产生提示，附件不进上下文。—
`test_unsupported_attachment_notice`

### AC-5 附件读取不越权

附件 `datas` 在 execution user 身份下读取；Live Chat bot 读不到访客附件时
fail closed（跳过 + 提示，不 sudo、不换执行主体）。— `test_attachment_read_no_sudo`

### AC-6 无附件回归

无附件消息行为不变：文本回帖、队列生命周期、typing 指示均不受影响。—
`test_no_attachment_unchanged`

## 运行方式

```bash
docker exec odoo odoo -c /etc/odoo/odoo.conf -d <db> \
  -i llm_discuss --test-enable --test-tags /llm_discuss \
  --stop-after-init --workers=0 --no-http
```

测试 mock provider adapter（`selection_value` + `mock.patch.object`，见
`llm/tests/common.py`）；无网络、无 API key。核心 `llm` 改动（invoke 链透传
`attachment_ids`）需同时跑 `/llm` 测试。

## 既有能力（待补测试）

以下为模块既有行为，当前无测试覆盖，随治理补 `tests/` 时一并补：

- 专用 bot 与 OdooBot 接管的触发规则（私聊 / mention / 两者，及接管五条件）。
- 栅栏队列：认领、fencing、超时 fail、不自动重放。
- 执行身份：`source_user`/`assistant_user` 模式、失效 fail closed、窄 sudo 边界。
- 页面上下文捕获与读权限校验。
- `odoobot_enabled` 单例约束。

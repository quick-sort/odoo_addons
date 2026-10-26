# discuss_agent — 验收标准

QC 唯一依据。每个条款可对应一个单元测试（`TransactionCase`，`@tagged("post_install", "-at_install")`）。

## 加载

1. `discuss_agent` 单独安装/升级后 Odoo 启动退出码为 0（manifest、XML、导入无误）。
2. core 依赖仅 `base` + `mail`，不 import `llm` / `agenthub`（依赖断言测试）。

## 多态解析

3. `discuss.agent` 记录 `res_model` / `res_id` 指向一个存在的记录时，
   `_discuss_resolve()` 返回该记录。
4. `res_model` 不存在、或 `res_id` 记录已被删除时，`_discuss_resolve()` 抛
   `UserError`（fail-closed），不静默返回空。
5. 目标模型未实现 `_discuss_execute` 时，`_discuss_execute()` 抛 `UserError`。

## 触发

6. `_discuss_should_trigger` 跳过：bot 自己的消息、非 `comment` 消息。
7. `direct_chat` 模式：仅 1:1 私聊且 bot 为成员时返回 True。
8. `mention` 模式：仅 `partner_ids` 含 bot 时返回 True。
9. `both` 模式：私聊或 @mention 任一命中返回 True。
10. 非内部用户（portal/public）`_discuss_user_can_use_agent` 返回 False。

## 入队

11. 触发后 `_discuss_enqueue_reply` 创建一条 `discuss.reply.job`，且
    `source_user_id` / `reply_partner_id` 分别正确固化。
12. 同 `(agent, message)` 重复入队幂等：第二次返回 False，不产生第二条 job。
13. dispatch 过程中某 agent 抛异常，不影响用户消息落库（不回滚消息）。

## 完成

14. `_claim_pending` 原子认领一条 pending，`state` 变为 processing，`claim_token`
    非空。
15. `_execution_user_and_company` 在 source_user 失效时抛 `UserError`。
16. `_complete({"result_html": "..."})` 回帖且作者 = `reply_partner_id`，`state`
    变 done。
17. `_complete` 收到空结果返回 False，不置 done。
18. `_complete_error(err)` 置 error 并记录 `error_message`。

## 页面上下文

19. `_discuss_normalize_page_context` 对无读权限的 `res_model`/`res_id` 丢弃
    `res_id`，不保留越权引用。
20. `_build_background` 在 execution user 无读权限时返回不含 `record` 的
    background，不升级 sudo。

## typing

21. `_set_bot_typing(True)` 对 reply_partner 所在 channel member 触发
    `_notify_typing(True)`。
22. 无其他 active job 时 `_clear_bot_typing_if_idle` 清除 typing。

## 生命周期 / fencing / GC

23. `_lock_owned_claim(claim_token)` 仅当 state=processing 且 token 匹配时返回
    True。
24. `_expire_stale_jobs` 把超时 processing 置 error，error_message 标注
    timed out，不自动重放。
25. `_gc_processed_jobs` 清理超过保留期的 done/error 记录。
26. `_process_one` 在 fencing token 失效时丢弃结果（LostQueueClaimError），
    不回帖、不置 done。
27. `_process_pending(agent_types=["llm"])` 只认领 agent_type=llm 的 job。

## 附件透传

28. `_discuss_enqueue_reply` 把 `message.attachment_ids` 快照进 job 的
    `attachment_ids`。
29. `_process_one` 把 job 的 `attachment_ids` 经
    `_discuss_execute(attachment_ids=...)` 传给 responder。
30. `llm.agent._discuss_execute` 把 `attachment_ids` 下传
    `_invoke_with_background`，最终到 `thread.generate`。

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

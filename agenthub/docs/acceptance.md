# agenthub — 验收标准（QC 唯一依据）

## 测试边界

- **Odoo addon**：`docker exec odoo odoo -c /etc/odoo/odoo.conf -d <test_db> -i agenthub --test-enable --test-tags /agenthub --stop-after-init --workers=0 --no-http`。覆盖模型/约束、component 扩展点、publish outbox、recorder 幂等、config 快照、Discuss 投影、token/权限。
- **Relay**：独立服务，由 relay 仓库的 contract/integration tests 覆盖 envelope、路由、状态机、WebSocket、租约、背压、DLQ、bot lease、HA 重连。
- **集成**：Odoo 侧使用 fake relay + fake channel，保证无外部网络/API key 也能跑。
- 本文的 AC 编号是验收合同；relay 相关条目标注 `[relay]`，其测试不在本 addon 的 `tests/` 内。

## 1. 装载与依赖

- [ ] **AC1** 模块干净装载：`-u agenthub` 退出码 0。
- [ ] **AC2** `depends` 只含基础设施（`component`、`mail` 等），**不含** `llm`、不含任何具体 channel/agent addon。测试断言依赖列表。

## 2. 数据模型

- [ ] **AC3** 模型存在：`agenthub.channel`、`agenthub.agent`、`agenthub.thread`、`agenthub.turn`、`agenthub.command`、`agenthub.identity`、`agenthub.binding`、`agenthub.delivery`、`agenthub.publish`，以及 `agenthub.record.cursor`。
- [ ] **AC4** core 不预置具体类型：`channel_type` / `agent_type` 在 core 源码里为 `selection=[]`（代码审查；运行时由 AC2 保证）。
- [ ] **AC5** `agenthub.channel` / `agenthub.agent` 继承 `collection.base`（行为上有 `work_on()`）。
- [ ] **AC6** `agenthub.thread` 继承 `mail.thread`；唯一约束 `(channel_id, peer_ref, agent_id)` 生效；Discuss-only thread 可只挂 `discuss_channel_id`（`channel_id` 为空）；`relay_thread_key` 唯一。
- [ ] **AC7** `agenthub.agent` 具备 `runtime`、`owner_user_id`、`user_id`、`partner_id`、`token_hash`、`state`、`last_seen`；活跃 agent 的 `user_id` 唯一。
- [ ] **AC8** `mail.message` 具备 `agenthub_role`、`agenthub_body_json`、`agenthub_is_error`、`agenthub_content`、`agenthub_relay_message_id`、`agenthub_relay_turn_id`、`agenthub_stream_id`、`agenthub_external_id`、`agenthub_reply_to_external_id`；以及 `agenthub.mt_user/assistant/tool/system` subtypes。
- [ ] **AC9** `agenthub.delivery` 只作审计副本：不存在以它为热队列的轮询代码；不再用 `mail.message.agenthub_delivery_state` 驱动投递。
- [ ] **AC10** `agenthub.publish` outbox 与 `agenthub.record.cursor` 存在，字段满足 AC15/AC17。

## 3. 扩展点

- [ ] **AC11** 抽象 component `agenthub.channel.adapter` / `agenthub.agent.adapter` 存在；未实现类型时抛 `NotImplementedError`。
- [ ] **AC12** 用 usage 后缀解析：`WorkContext(collection=channel).component(usage=channel_type)` 能解析到对应实现，且不同 type 的 usage 互不冲突。
- [ ] **AC13** `runtime=relay` 的 agent 不要求进程内 adapter；Odoo 创建 turn 并写 publish outbox 即可。
- [ ] **AC14** `runtime=in_process` 的 agent 仍通过 adapter `reply()` 执行，且运行在 `_agent_env()` 下。

## 4. Odoo publish 与 recorder

- [ ] **AC15** Discuss 入站消息与 `agenthub.publish` outbox 在同一事务写入；worker 推送失败可重试；消息不会因推送失败而丢失。
- [ ] **AC16** publish 幂等：重复 `event_id` 时 relay 返回 duplicate；Odoo outbox 标记 sent，不重复投递。
- [ ] **AC17** recorder 从 relay `record` 流按 cursor 拉取；批量写入以 `agenthub_relay_message_id` + `agenthub_stream_id` 幂等；cursor 只在数据库提交后推进。
- [ ] **AC18** 默认只落最终消息：`message.updated` 不写 `mail.message`；`message.final` 创建/更新一条消息；不存在每条流式帧一行。
- [ ] **AC19** Discuss 投影与去重：用户原始消息已由 Odoo 落库，publish 事件带 `meta.origin_record_id`，recorder 不重复创建；agent 最终消息以 service user 身份出现在对应 `discuss.channel`；不会把 agent 自己的消息再次当作入站（无回声环）。
- [ ] **AC20** cron/命令：`agenthub.command` 与 publish outbox 同事务创建；`reply_mode` 为 `none`/`owner`/`thread` 时分别只落库/通知 owner/回到指定 thread。
- [ ] **AC21** recorder lag 可观测；超过阈值时对 relay 入站施加背压并告警，不静默丢消息。

## 5. 路由与 relay 状态机

- [ ] **AC22** `[relay]` 外部渠道：`identity + binding` 能解析到 agent；`thread_key` 确定性生成；路由过程不查询 Odoo thread 表。
- [ ] **AC23** `[relay]` Discuss：Odoo publish 事件携带 `thread_key` 与 `agent_id`，relay 直接入 agent inbox，不做二次解析。
- [ ] **AC24** `[relay]` 未知 identity/binding 时拒绝并向 Odoo 发 control 事件；不静默回退到默认 agent。
- [ ] **AC25** `[relay]` 同一 thread 同时只有一个活跃 turn；后续消息进入 FIFO backlog；活跃 turn 结束后依次处理。
- [ ] **AC26** `[relay]` agent WebSocket 认证：token hash 校验、`agent_id` 与 token 匹配；越权领取其他 agent 的 inbox 被拒绝并审计。
- [ ] **AC27** `[relay]` delivery 状态机：`queued → claimed → running → done`；租约过期回到 `queued`；超过最大尝试进 DLQ；至少一次投递。
- [ ] **AC28** `[relay]` channel outbox 状态机：`pending → sending → sent`；失败退避重试；超过上限进 dead-letter。
- [ ] **AC29** `[relay]` presence：`online / busy / draining / offline`；心跳超时转 offline；离线 agent 的队列有 TTL。
- [ ] **AC30** `[relay]` 企微 bot 租约：同一 `bot_id` 同时只有一个 gateway 实例持有连接；实例故障后租约过期由其他实例接管，不发生互踢。
- [ ] **AC31** `[relay]` 配置同步：版本化快照原子替换；token/渠道密钥轮换后旧连接按策略失效；重载后路由立即使用新配置。
- [ ] **AC32** `[relay]` 多实例/重连：agent 断线可重连到其他实例，按游标恢复；未 ack 的 delivery 重新投递。

## 6. 背压与可靠性

- [ ] **AC33** `[relay]` 每 agent/channel 有队列和未 ack 上限；超限时拒绝新入站（429/503），已接受消息不被丢弃。
- [ ] **AC34** `[relay]` durable log 在 relay 重启后保留；可按 cursor 重放；已接受但未投递的消息不丢。
- [ ] **AC35** `[relay]` 毒消息/超限投递进 DLQ；支持人工重放；DLQ 不阻塞主队列。
- [ ] **AC36** `[relay]` `record` 流保留期内不丢失；lag 超阈值告警并背压；不允许静默丢弃归档事件。

## 7. XML

- [ ] **AC37** 所有 view/security/data XML 过 `xml.dom.minidom` 解析。

## 8. 不联网

- [ ] **AC38** Odoo 测试在无外部 API key、无网络下可过；relay 测试使用 fake channel/agent，不发真实企微请求。

## 9. 执行身份与权限

- [ ] **AC39** `agenthub.agent` 的 `user_id` 必须是内部用户（`share=False`）且 `active=True`；违规抛 `ValidationError`；允许 `user_id == owner_user_id`。
- [ ] **AC40** `_agent_env()` 返回绑定执行用户的 env：`uid == user_id`、`su == False`；从 `sudo()` 调用时仍 `su == False`。
- [ ] **AC41** `in_process` agent 的 `reply()` 在 `_agent_env()` 下执行；`relay` agent 的 token 只能访问自己的 inbox，Odoo 权限不被绕过。
- [ ] **AC42** Discuss 中 agent 的显示身份是 `user_id.partner_id`；消息作者为该 partner；审计可区分人与 agent。
- [ ] **AC43** record rule：`agenthub.group_agenthub_user` 只能看到 `owner_user_id == 自己` 的 agent 及其 thread；`agenthub.group_agenthub_admin` 看全部。

## 10. 管理 UI、Token 与命令

- [ ] **AC44** 存在 `Agents` 的 list/form 视图与菜单。
- [ ] **AC45** token 生成时只展示一次，数据库存 `token_hash`；支持轮换；relay 配置快照拿到 hash。
- [ ] **AC46** 存在 `Identities`、`Bindings`、`Commands` 的管理入口（或嵌入 agent/channel 表单）。
- [ ] **AC47** `agenthub.command` 可由 cron 创建；表单支持 `reply_mode`。

## 11. 规模与性能

- [ ] **AC48** `[relay]` 单 relay 实例支持 100+ agent WebSocket 连接；目标吞吐 50 万消息/天；投递 p95 延迟满足约定 SLO。
- [ ] **AC49** `[relay]` 上述负载下无消息丢失；租约过期率、DLQ 大小在可接受范围；record lag 可观测。
- [ ] **AC50** Odoo recorder 批量写入，避免逐条 `message_post`；cron 版本每分钟拉取，cursor/lag 可观测；<5 秒 SLO 由后续长轮询 worker 验收（v1 不做）。
- [ ] **AC51** 已有 legacy 部署升级后，legacy Odoo WS 与 relay gateway 不会同时持有同一个 `bot_id`（配置校验或启动检查）。

## 12. Recorder 细节

- [ ] **AC52** recorder 拉取请求带 `X-AgentHub-Recorder-Token`；未授权返回 401；成功后推进 cursor 并 ack。
- [ ] **AC53** 幂等：同一 relay `message_id` / `stream_id` 重复处理不产生重复 `mail.message`。
- [ ] **AC54** Discuss 投影：agent 消息以 service user 身份出现在 `discuss.channel`；外部渠道消息写入 `agenthub.thread`。
- [ ] **AC55** `meta.origin_record_id`（`mail.message,<id>`）链接 Odoo 已落库的 Discuss 用户消息，不重复创建。
- [ ] **AC56** `delivery.*` 写 `agenthub.delivery` 审计；`presence.changed` 更新 `agenthub.agent.state/last_seen`。
- [ ] **AC57** `message.updated` 默认忽略，只落 `message.created` / `message.final` 的最终消息。
- [ ] **AC58** 处理事件失败时不推进 cursor，下一轮至少一次重放。

## 13. Publish hooks 与配置快照

- [ ] **AC59** `agenthub_discuss` 安装后，绑定 thread 的 Discuss 用户消息自动生成 `message.created` publish；agent service user / OdooBot 回帖不回灌；同一 `mail.message` 幂等。
- [ ] **AC60** `agenthub.command` 进入 `queued` 时自动生成 `command.created` publish；draft 不发送，`action_queue` 后发送；`reply_mode=thread` 必须有 thread。
- [ ] **AC61** `agenthub.publish._enqueue` 在事务提交后尝试立即推送；失败由 publish cron 重试。
- [ ] **AC62** `GET /agenthub/relay/config` 需要 `X-AgentHub-Config-Token`：未配置 token 返回 503，错误 token 返回 401，正确 token 返回版本化快照。
- [ ] **AC63** `[relay]` 配置拉取循环按版本更新 agent token / identity / binding 缓存，版本不变时不重复应用。

## 14. v1 不做（后续验收）

- Relay 多实例 router 分片、跨机房。
- Discuss 流式中间态投影。
- 图形化 DLQ/replay。
- NATS JetStream 替代实现、多区域部署。
- 语义路由/LLM 分类。
- exactly-once 投递。
- 群聊/多用户会话的完整语义。

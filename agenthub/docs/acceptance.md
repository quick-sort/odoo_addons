# agenthub — 验收标准（QC 唯一依据）

每个功能点至少对应一个测试（`tests/`）。跑法：
`docker exec odoo odoo -c /etc/odoo/odoo.conf -d <test_db> -i agenthub --test-enable --test-tags /agenthub --stop-after-init --workers=0 --no-http`。

## 1. 装载与依赖

- [ ] **AC1** 模块干净装载：`-u agenthub` 退出码 0。
- [ ] **AC2** `depends` 只含基础设施（`component`、`mail` 等），**不含** `llm`、
  不含任何具体 channel/agent addon。测试断言依赖列表。

## 2. 数据模型

- [ ] **AC3** 三个模型存在：`agenthub.channel`、`agenthub.agent`、
  `agenthub.thread`；且 `mail.message` 上存在 `agenthub_*` 扩展字段。
- [ ] **AC4** core 不预置任何具体类型：`channel_type` / `agent_type` 在 core
  源码里声明为 `selection=[]`（代码审查项；运行时等价由 AC2 的「core 不依赖
  任何 channel/agent addon」保证——装了扩展 addon 后 selection 会被
  `selection_add` 填充，不再是空）。
- [ ] **AC5** `agenthub.channel` / `agenthub.agent` 继承 `collection.base`
  （行为上表现为有 `work_on()` 方法）。
- [ ] **AC6** `agenthub.thread` 继承 `mail.thread`，唯一约束
  `(channel_id, peer_ref)` 生效：同 channel 同 peer 建第二条 thread 抛约束错误。
- [ ] **AC7** `mail.message` 具备 `agenthub_role`、`agenthub_direction`、
  `agenthub_external_id`、`agenthub_reply_to_external_id`、
  `agenthub_delivery_state`、`agenthub_stream_id`、`agenthub_content` 字段。

## 3. 扩展点（component 契约）

- [ ] **AC8** 存在抽象 component `agenthub.channel` 与 `agenthub.agent`，契约
  方法（`channel.send`、`agent.reply`）未实现类型时抛 `NotImplementedError`。
- [ ] **AC9** 用 usage 后缀解析：`WorkContext(collection=channel).component(
  usage=f"agenthub.channel.{channel_type}")` 能解析到对应实现，且不同
  `channel_type` 的 usage 互不冲突。

## 4. 路由（core 中介）

- [ ] **AC10** 给定一个 inbound `mail.message`，路由层能按
  `(channel_id, peer_ref)` 找到/创建 thread，并调用 `thread.agent_id` 的
  `reply()`（用 mock agent 断言被调用）。
- [ ] **AC11** agent 产出的 outbound message 会被交给 `channel.send()`（用 mock
  channel 断言被调用）。
- [ ] **AC12** 关联字段贯通：channel 归一化填 `agenthub_external_id` /
  `agenthub_reply_to_external_id`，agent 用它们匹配回原 outbound（用 mock 断言
  匹配逻辑，不依赖真实 channel）。

## 5. 投递状态机

- [ ] **AC13** outbound message 建时为 `agenthub_delivery_state=pending`，
  `send()` 成功后置 `sent`。
- [ ] **AC14** 投递失败置 `failed`。
- [ ] **AC15** 跨进程投递队列语义：`pending` 出站消息可被按 channel 查询到，
  用于 gevent 连接循环轮询（断言查询域按 `agenthub_delivery_state=pending` +
  所属 thread 的 `channel_id` 过滤）。

## 6. XML

- [ ] **AC16** 所有 view/security/data XML 过 `xml.dom.minidom` 解析。

## 7. 不联网

- [ ] **AC17** 全部测试在无外部 API key、无网络下可过（core 本身无出网，
  出网只在 channel 实现 addon）。

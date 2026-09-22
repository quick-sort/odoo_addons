# agenthub_openclaw — 验收标准（QC 唯一依据）

跑法：
`docker exec odoo odoo -c /etc/odoo/odoo.conf -d <test_db> -i agenthub_openclaw --test-enable --test-tags /agenthub_openclaw --stop-after-init --workers=0 --no-http`。

测试用构造的 `mail.message` 记录验证 agent 语义，**不依赖真实 OpenClaw、
不联网、不 import 任何 channel addon**。

## 1. 装载与注册

- [ ] **AC1** 模块干净装载：`-u agenthub_openclaw` 退出码 0。
- [ ] **AC2** `agenthub.agent` 的 `agent_type` 出现 `openclaw` 值。

## 2. 流式累积

- [ ] **AC3** 多个 `finish=false` 增量帧 + 一个 `finish=true` 终帧（同一
  `stream.id`）累积成完整回复文本。
- [ ] **AC4** `finish=true` 判定收尾；未收到终帧不算完成（状态不置完成）。

## 3. 内容归一化

- [ ] **AC5** `<think>…</think>` 块与正文分离：正文不含 think 内容。
- [ ] **AC6** markdown 正文原样保留（不做破坏性改写）。

## 4. 关联

- [ ] **AC7** 用 `agenthub_reply_to_external_id` 把回包关联回原 outbound
  （断言匹配逻辑，构造两条消息验证不会串线）。

## 5. 产出

- [ ] **AC8** `reply()` 返回归一化后的可见文本（`<think>` 已剥离）。

## 6. 解耦

- [ ] **AC9** 本 addon 的依赖列表不含 `agenthub_wecom`；测试断言不 import 任何
  channel addon。

## 7. XML / 不联网

- [ ] **AC10** view/security/data XML 过 `xml.dom.minidom`。
- [ ] **AC11** 全部测试无网络可过。

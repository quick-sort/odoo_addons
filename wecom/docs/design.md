# 系统设计（design）

## 模型

| 模型 | 职责 |
|---|---|
| `wecom.app` | 应用凭证 + access_token 缓存 + SDK 客户端工厂 + 发送/撤回的底层接口 |
| `wecom.app.message` | 一次发布的载体与历史：内容、接收范围、状态机、msgid、撤回 |
| `wecom.app.message.article` | 图文消息子表（news / mpnews 的文章） |
| `wecom.department` / `wecom.user` | 通讯录本地缓存 |

`wecom.app.message` 状态机：`draft → sent / failed`，`sent → recalled`（撤回成功）。
撤回是同步按钮操作，失败不改变状态。

## SDK 与 token

- 使用 `wechatpy.enterprise.WeChatClient`。
- `WecomAppSessionStorage` 实现 wechatpy 的 session 协议（get/set/delete），
  把 access_token 持久化到 `wecom.app` 记录（含过期时间），实现跨进程缓存与自动刷新。

## 发送链路

```
界面按钮 action_publish ─┐
外部模块 send_message() ─┴→ 创建/复用 wecom.app.message 记录
                              → message.send()          # 回写状态/结果/msgid
                              → _send_to_wecom()        # 上传素材、组装
                              → app._send_message()     # textcard，一次 message/send
                              / app._send_articles()    # news/mpnews，按 8 篇分批
```

- 每批 `message/send` 调用企业微信返回一个 `msgid`。
- 单批：msgid 即响应里的 `msgid` 字段。
- 多批：`_merge_results()` 把各批 msgid 收集为换行分隔的字符串，随合并结果返回。

## 撤回链路（本次新增）

- 企业微信官方接口：`POST /cgi-bin/message/recall`，body `{"msgid": "..."}`，
  仅 24 小时内可撤回。
- **wechatpy（含 1.8.18 与 GitHub master）没有封装该接口。**
  不换 SDK、不绕开 SDK：`WeChatClient` 基类的公开 `post(endpoint, data)` 方法
  就是所有 send 方法的底层通道（自动拼 `https://qyapi.weixin.qq.com/cgi-bin/`、
  注入 access_token、JSON 编码、`errcode != 0` 抛 `WeChatClientException`、
  token 过期自动重试），因此撤回直接：

  ```python
  client.post('message/recall', data={'msgid': msgid})
  ```

- `wecom.app.message.action_recall()`（界面按钮）逐个 msgid 撤回：
  1. 客户端预检：仅 `sent` 状态、有 msgid、`send_date` 在 24 小时内，否则 `UserError`（友好提示，不调 API）；
  2. 逐个调 `wecom.app._recall_message(msgid)`；
  3. 全部成功 → `state='recalled'` + `recall_date`；任一失败 → 错误经**独立游标**追加进
     `result`（`_write_recall_failure`），状态不变，抛 `UserError`。
- 服务端 errcode 是最终裁决（如刚好卡在 24h 边界），预检只是提前给出中文提示。

### 失败簿记必须走独立游标

`UserError` 会让 Odoo 回滚整个请求事务——在当前事务里先写 `result` 再抛异常，
写入会被一并回滚，用户永远看不到失败原因（Odoo 测试的 `assertRaises` 以同样方式
回滚，CI 正是靠这一点抓住了最初的错误实现）。因此撤回失败信息用
`env.registry.cursor()` 开新游标写入，正常退出即提交，不受回滚影响；与 infohub
渠道失败簿记是同一模式。代价：只能更新已提交的行，行不存在则跳过。
TransactionCase 的类级数据同样不提交，故该路径的用例须自己在独立游标里
创建并发送记录（真实提交）后再触发撤回失败。

## 被否决的方案

- **自建 requests 调撤回接口**：绕开了 token 缓存、异常翻译、过期重试，重复造轮子。否决。
- **单独建 `wecom.app.message.msg` 子表存 msgid**：一条消息最多几批（8 篇一批），
  Text 字段每行一个 msgid 足够，不值得一张表。否决。
- **撤回用 queue_job 异步**：单次调用毫秒级，异步反而让按钮反馈变慢、状态机复杂。否决。

## 约束（红线）

1. 其他模块发消息**只能**走 `wecom.app.send_message()`（自动留历史）；
   `_send_message()/_send_articles()/_recall_message()` 是模块内部接口，不得外部直调。
2. 底层所有企业微信调用必须经 `get_wecom_client()`（token 缓存生效的前提）。
3. 测试对 wechatpy 全 mock，不联网、不需要真实 CorpId。

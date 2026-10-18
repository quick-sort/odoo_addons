# 验收标准

每个功能点（编号对应 requirements.md）给出可验证标准；`tests/` 一一对应。
QC = 下表全绿 + 模块干净装载 + 测试不联网。

| # | 功能点 | 验收标准 | 测试 |
|---|--------|----------|------|
| A1 | 模块装载 | `-i wechat --stop-after-init` 退出码 0 | QC 命令本身 |
| A2 | 消息落库 | 创建 inbound 消息 log，msgid/from_user/msg_type/content 正确入库，msgid×公司 唯一约束生效 | `test_message_log.py` |
| A3 | 消息清理 | 超过保留天数的记录被 `_cleanup_old_messages` 删除，未过期保留 | `test_message_log.py` |
| A4 | 关键字匹配 | exact 相等命中；fuzzy 包含命中；regex 命中且非法 pattern 不抛异常；sequence 小者优先；命中后 reply_count/last_trigger_time 更新；不匹配返回 None | `test_message_rule.py` |
| A5 | 回复 payload | text/image/video/music/news 五类规则的 `get_reply_data()` 结构正确；默认回复与关注回复同理 | `test_message_rule.py` |
| A6 | 约束 | 规则 keyword×match_type×公司 唯一；默认回复/关注回复每公司唯一 | `test_message_rule.py` |
| A7 | 关注生命周期 | subscribe 事件建档（openid/状态/时间，qrscene_ 前缀剥离，数字→qr_scene 字符串→qr_scene_str），重复关注更新不重复建；unsubscribe 置 unsubscribed；`_fetch_user_info` 被 mock，无网络 | `test_wechat_user.py` |
| A8 | 用户约束/查询 | openid×公司 唯一；tag 唯一性；`get_by_openid` 命中 | `test_wechat_user.py` |
| A9 | 菜单 JSON | 一级+子按钮结构生成微信格式 JSON（type/name/key/url/sub_button），带子按钮的父按钮不含 type | `test_wechat_menu.py` |
| A10 | 菜单同步 | `action_sync` 调用 `/menu/create`（mock wechat_post），成功置 synced，errcode≠0 置 failed+last_error | `test_wechat_menu.py` |
| A11 | 模板消息 | `send_template_message` 走 wechat.request（mock），errcode=0 成功且计数+1，errcode≠0 失败不改计数 | `test_template_mass.py` |
| A12 | 群发准备 | `_prepare_message` 对 text/image/video/news 生成正确 body 与 filter（无标签→is_to_all）；`_do_send` 成功置 sent+msg_id，失败置 failed+error_msg（mock wechat_post） | `test_template_mass.py` |
| A13 | token 生命周期 | 未配置凭证抛 UserError；缓存命中不重复请求；errcode 40001 → 失效重试一次（mock requests + WeChatClient） | `test_wechat_request.py` |
| A14 | 被动回复渲染 | `_render_reply_xml` 对 text/news 生成合法 XML 信封（ToUserName 取来源、Content 正确） | `test_callback.py` |
| A15 | 回调分发 | `_on_text` 命中规则返回 payload；未命中且默认回复关闭返回 None；subscribe 事件建档并返回关注回复（mock，无网络） | `test_callback.py` |
| A16 | XML well-formed | 本 addon 全部 XML 过 minidom | QC 命令本身 |

## 测试环境约定

- 全部 `@tagged("post_install", "-at_install")` + `TransactionCase`。
- 一切出站 HTTP / wechatpy 客户端均 mock：
  `wechat.request._get_access_token`、`wechat.request.wechat_post/get`
  是统一 mock 点，业务测试无需逐处 patch。
- 控制器测试直接实例化 `WechatMpCallback` 调 `_on_*`/`_render_reply_xml`
  纯方法（在事务内通过 `request.env` 访问 ORM），不发起真实 HTTP。

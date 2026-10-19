# 系统设计

## 合并决策（本 addon 的由来）

源仓库把公众号能力拆成 `wechat_base` + `wechat_mp` 两个 addon。合并进本
仓库时收敛为一个 `wechat` addon，理由：

1. `wechat_base` 没有独立价值——它的全部模型（token 管理、消息基表、
   用户 mixin）只为公众号服务；拆分的唯一受益者（login/payment/work）
   均不在本仓库范围。
2. 两模块间的耦合点（`wechat.message` ↔ `wechat.mp.message.log` 双表、
   菜单模型 ↔ base 的假同步按钮）在拆分状态下产生过真实 bug（见
   「移植时修复的源缺陷」）。
3. 命名统一：模型从 `wechat.mp.*` 改为 `wechat.*`，消除 `mp` 前缀这一
   分层痕迹。

**被否决方案**：保持 base/mp 两 addon 结构。否决原因如上 1/2——只为
「将来 login/payment 进来」保留分层是投机设计；真进来时它们依赖
`wechat` 即可。

## 数据模型

```
res.company (扩展)
  ├─ wechat_app_id / wechat_app_secret / wechat_token / wechat_aes_key
  └─ wechat_access_token / wechat_token_expire   (展示用镜像, 真相在 config_parameter)

wechat.request                (AbstractModel — API 网关, 见下)

wechat.user.mixin             (AbstractModel — openid/unionid/关注状态等共享字段)
wechat.user                   公众号关注者 (多公司, openid×公司唯一)
wechat.user.tag / wechat.user.group

wechat.message                消息基表 (msgid×公司唯一)
wechat.message.log            = wechat.message + 回复跟踪/关联用户 (prototype inheritance)
wechat.message.cron           (AbstractModel — 清理 cron 入口)

wechat.message.rule           关键字规则 (keyword×match_type×公司唯一)
wechat.auto.reply.default     默认回复 (每公司一条)
wechat.subscribe.reply        关注回复 (每公司一条)

wechat.menu / wechat.menu.button   菜单 + 自引用按钮树
wechat.template.message       模板注册表
wechat.mass.message           群发 (name×公司唯一)
```

## 关键设计

### wechat.request：唯一 API 出口

所有微信 API 调用（模板、群发、菜单、用户信息、token 本身）经
`wechat.request` 抽象模型：

- token 缓存于 `ir.config_parameter`（`wechat.access_token.<company_id>`，
  company 间隔离），过期前 5 分钟缓冲；
- 响应 `errcode ∈ {40001, 42001}` → 失效缓存 → 重取 → 重试一次；
- URL 统一挂 `https://api.weixin.qq.com/cgi-bin` 前缀，调用方只传 path。

公司表单上的 `wechat_access_token` 字段只是该缓存的展示镜像，**不是**
读取来源——源实现中各模型直接读该字段，token 一过期（约 2 小时）所有
出站功能静默失败，这是移植时统一修掉的缺陷。

### 回调双路由 + 被动回复

- `/wechat/webhook/<company_id>`：基类控制器（验证/解密/解析），不做业务；
- `/wechat/mp/webhook/<company_id>`：MP 子类控制器，override
  `_process_payload`，接自动回复。

被动回复协议要求把回复 XML 作为 HTTP 响应体返回。处理器（`_on_text`
等）返回 **reply payload dict 或 None**；`_process_payload` 把非 None
payload 渲染成微信回复 XML 返回，否则回 `success`。（源实现生成了回复
Response 却被丢弃、恒返 `success`，被动回复从未生效。）

`wechatpy` 解析结果统一被 `_extract_msg_data` 摊平为微信原生字段名
dict（`MsgType`/`FromUserName`/…），处理器只认这一种格式。

### 多公司

公司级凭证 + 全模型带 `company_id` + ir.rule 多公司过滤。回调 URL 内嵌
公司 ID 区分租户。

## 移植时修复的源缺陷

| 源缺陷 | 修复 |
|---|---|
| `wechat_menu_root` 菜单被 mp 视图引用但从未定义 | 新建菜单树 `views/wechat_menus.xml` |
| 公司表单「测试连接」按钮无对应方法 | `action_test_wechat_connection` 实现 |
| mp 各模型直读 `company.wechat_access_token`，过期即失效 | 全部改走 `wechat.request` |
| 回调被动回复 Response 被丢弃 | payload-dict 协议（见上） |
| mp_api `type='json'` + `methods=['GET']`（Odoo JSON 路由仅支持 POST） | 统一 POST |
| `push_menu` 中 `menu.write` 被 `if 'menu' in context` 挡死 | 修正常量引用 |
| 默认回复/关注回复模型无视图无菜单，功能不可达 | 补表单视图 + 配置菜单 |
| 菜单同步按钮是空壳（`sync_to_wechat` return True） | 接真实 `/menu/create`，另加远程删除 |
| `wechat.message` 用已废弃的 `create` 单条签名 | `@api.model_create_multi` |
| 安全组挂在已删除的 `module_category_general` / 重复两套用户组 | 单套组 + 有效分类 |
| `<tree>` / `attrs` / wizard footer 等 Odoo ≤16 写法 | Odoo 19 语法全量改写 |

## 依赖

- Odoo: `base`
- Python: `wechatpy`（manifest `external_dependencies` 声明；未安装时
  模块可装载，回调签名验证降级拒绝、token 获取报明确错误）
- 群发接口按「认证服务号」能力假设（`/message/mass/sendall`）。

## 约束（红线）

1. **所有微信 API 出站调用必须经 `wechat.request`**，禁止在模型/控制器里
   直接拼 `access_token` 发 HTTP。
2. **回调被动回复只能通过 `_process_payload` 的 payload-dict 协议返回**，
   处理器不得自行构造 HTTP 响应。

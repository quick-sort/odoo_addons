# InfoHub — 验收标准

> 这是 QC 的唯一依据。每个功能点（AC-x）必须有一个对应的测试；测试全绿才算通过。

## AC-1 模型分离

**要求**：source 与 channel 是独立模型，互不依赖。

- 测试：`test_source_is_separate_from_channel`
- 测试：`test_item_requires_title_and_channel`

## AC-2 渠道类型由 addon 扩展

**要求**：core 的 `channel_type` 为空选择，由渠道 addon `selection_add` 填充；
字段本身必须 required。

- 测试：`test_channel_type_is_extended_by_channel_addons`

## AC-3 core 不依赖 llm

**要求**：`infohub` 的依赖列表只含 `base`、`component`、`queue_job`，不含 `llm`。

- 测试：`test_core_does_not_depend_on_llm`

## AC-4 内容纯文本副本

**要求**：`content_text` 由 `content` 派生（去 HTML 标签），显式传入则保留原值。

- 测试：`test_content_text_derived_from_html`
- 测试：`test_content_text_strips_tags`
- 测试：`test_explicit_content_text_is_preserved`

## AC-5 渠道内去重

**要求**：同一 `(channel_id, external_id)` 重复建会被拒绝；不同 channel 的相同
external_id 是两条。

- 测试：`test_duplicate_external_id_in_same_channel_is_rejected`
- 测试：`test_same_external_id_in_different_channels_is_allowed`
- 测试：`test_ingest_deduplicates_localized_variants`（同一稿件 de/fr 两条 → 1 条）
- 测试：`test_ingest_keeps_items_with_different_identifiers`

## AC-6 过滤域

**要求**：`filter_domain` 支持 `=`、`!=`、`<`、`>`、`ilike` 等操作符，支持 `&`、
`|`、`!` 前缀表达式；空域全保留；`not ilike` 在字段缺失时保留。

- 测试：`test_match_item_simple_equality`
- 测试：`test_match_item_ilike_is_case_insensitive`
- 测试：`test_match_item_empty_domain_keeps_everything`
- 测试：`test_match_item_or_expression`
- 测试：`test_match_item_not_expression`
- 测试：`test_match_item_missing_field_with_negative_operator`

## AC-7 外部身份提取

**要求**：`external_id` 按 `id → identifier → guid → external_id → link → url`
取第一个非空值；重复 tag 的 list 取第一个元素；都无则空。

`identifier` 优先于 `guid`：多语言发布的每个语言版本有独立 URL，但共享发布方
编号。

- 测试：`test_external_id_prefers_identifier_over_guid`
- 测试：`test_external_id_prefers_id_over_identifier`
- 测试：`test_external_id_reads_identifier_from_raw_data`
- 测试：`test_external_id_takes_first_value_when_repeated`
- 测试：`test_external_id_prefers_guid_over_url`
- 测试：`test_external_id_falls_back_to_guid_without_identifier`
- 测试：`test_external_id_falls_back_to_url`
- 测试：`test_external_id_empty_when_nothing_usable`
- 测试（RSS 端到端）：`test_identifier_is_kept_for_deduplication`、
  `test_localized_variants_are_deduplicated`

## AC-8 日期解析容错

**要求**：`published_at` 能解析 ISO 日期；解析失败回退到当前时间（不抛异常）。

- 测试：`test_published_at_parses_iso`
- 测试：`test_published_at_falls_back_to_now_on_garbage`

## AC-9 入库管线

**要求**：`_ingest` 创建条目、跳过无标题条目、渠道内去重、尊重 filter_domain、
把条目归属到已知 source、无法确定时留空。

归属由 `_resolve_source` 承担，三步由窄到宽，**每步都只比整个域名或整个名称**，
不做松散子串匹配，所以不会猜错来源：

1. 条目链接的域名 ↔ `infohub.source.url`
2. 渠道读出的来源名 ↔ `infohub.source.name`（`=ilike`）
3. 上两者里的域名 ↔ `infohub.source.description` 里的域名线索。线索可写裸域名
   （`nature.com`），也可写完整地址（`newsletters@nature.com`）。域名按边界比较，
   所以 `fiercepharma.com` 命中 `news@fiercepharma.com` 与
   `mail.fiercepharma.com`，但**不命中** `notfiercepharma.com`。

第 3 步是入站简报的必经之路：它既没有条目链接，`source()` 读出的又是一整串
`Name <address@domain>`，永远不等于 source 的 `name`。

三步都不命中则留空。

- 测试：`test_ingest_creates_items`
- 测试：`test_ingest_skips_item_without_title`
- 测试：`test_ingest_deduplicates_within_channel`
- 测试：`test_ingest_honours_filter_domain`
- 测试：`test_ingest_filter_on_missing_raw_field_drops_item`
- 测试：`test_ingest_links_known_source_by_url`
- 测试：`test_ingest_leaves_source_empty_when_unknown`
- 测试：`test_ingest_links_source_from_the_channel_payload`
- 测试：`test_ingest_links_source_from_the_sender_domain`
- 测试：`test_ingest_sender_domain_matches_a_subdomain`
- 测试：`test_ingest_matches_a_description_holding_a_full_address`
- 测试：`test_ingest_source_clue_matches_on_a_domain_boundary_only`

## AC-10 SSRF 防护（url_guard）

**要求**：拒绝非 http/https scheme、空/无主机名、本机名、字面量私网 IP、IPv4-mapped
IPv6、解析到私网的主机名；多地址中任一为私网即拒绝；`resolve=False` 不发 DNS；
`allow_private` 显式放行开发环境。

- 测试：`TestUrlGuard` 全部 11 个方法

## AC-11 载荷页签的长内容换行

**要求**：Items 表单的两个载荷页签都要能在可视区域内完整阅读，不横向溢出、不需要
横向滚动。

- **Content**：`infohub.item.content` 里数据自身的换行必须保留。渠道用
  `_labelled()` 拼出的 header（Title / Feed / Author / Date / Categories）是逐行
  `\n` 分隔的，而 HTML 默认的 `white-space: normal` 会把单个换行折成空格 —— 五行
  挤成一行，越拉越长顶出表单。
- **Raw Data**：Odoo 19 的 `widget="json"` 就是一个 `<span t-esc>`，内容来自
  `JSON.stringify()` —— 单行、无缩进、没有任何可断行的空白。

修法是两个字段各带一个类（`o_infohub_item_content` / `o_infohub_raw_data`），由
`static/src/scss/infohub_item.scss` 统一给 `white-space: pre-wrap`（保留数据自带的
换行，同时仍在行尾折行）加 `overflow-wrap: anywhere`（连没有断点的长 token 也能断）。

两条实现约束，改之前先读：

1. 类挂在 `<field class="...">` 上，**不在外面套 `<div>`**。Odoo 的
   `Field.classNames` 会把 `props.class` 加到字段根节点上；套 div 会把 `content`
   从 `:first-child` 挤掉，丢掉 `form_controller.scss` 专门给 `.o_field_html`
   的页签内边距。
2. 选择器必须带这两个类，**不能直接写 `.o_field_json` / `.o_field_html`** ——
   `async_task` 也在三个字段上用 `widget="json"`，全局覆盖会改到别人的界面。

换行是浏览器行为，Python 断言不了。下面两个测试锁的是它赖以生效的两个前提，任一被
去掉都会「测试全绿但 bug 复发」：

- 测试：`test_item_form_hooks_both_payload_fields`
- 测试：`test_item_form_stylesheet_is_shipped`

## AC-12 手动抓取的用户反馈

**要求**：表单上的「Fetch Now」成功后返回 `display_notification` 客户端动作，
消息报告本次抓取的条目总数与新增/去重数；`next` 为 `reload`，让
`last_run_at` / `error_count` 跟着刷新。失败仍按既有路径抛错并记入
`error_count`。

- 测试：`test_action_fetch_reports_the_result`
- 测试：`test_action_fetch_reports_duplicates_on_the_second_run`

## AC-13 搜索时间过滤

Items 搜索面板的过滤项只有三个时间窗口：Last 1 Day / Last 7 Days / Last 30 Days。
都基于 `published_at`，用 `context_today() + relativedelta` 按用户当天计算；原有的
New / Accepted 状态过滤已移除。Group By（Source / Channel / Channel Type）保留。 —

- 测试：`test_item_search_filters_are_time_windows`

## 运行方式

```bash
# 跑 core 的全部测试
docker exec odoo odoo -c /etc/odoo/odoo.conf -d <db> \
  -i infohub --test-enable --test-tags /infohub \
  --stop-after-init --workers=0 --no-http
```

测试离线可跑（url_guard 用 mock，无网络、无 API key）。

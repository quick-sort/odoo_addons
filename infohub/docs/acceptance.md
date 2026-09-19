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

**要求**：`external_id` 优先取 guid/id，回退到 url；都无则空。

- 测试：`test_external_id_prefers_guid_over_url`
- 测试：`test_external_id_falls_back_to_url`
- 测试：`test_external_id_empty_when_nothing_usable`

## AC-8 日期解析容错

**要求**：`published_at` 能解析 ISO 日期；解析失败回退到当前时间（不抛异常）。

- 测试：`test_published_at_parses_iso`
- 测试：`test_published_at_falls_back_to_now_on_garbage`

## AC-9 入库管线

**要求**：`_ingest` 创建条目、跳过无标题条目、渠道内去重、尊重 filter_domain、
按 URL 匹配已知 source、未知 source 留空。

- 测试：`test_ingest_creates_items`
- 测试：`test_ingest_skips_item_without_title`
- 测试：`test_ingest_deduplicates_within_channel`
- 测试：`test_ingest_honours_filter_domain`
- 测试：`test_ingest_filter_on_missing_raw_field_drops_item`
- 测试：`test_ingest_links_known_source_by_url`
- 测试：`test_ingest_leaves_source_empty_when_unknown`

## AC-10 SSRF 防护（url_guard）

**要求**：拒绝非 http/https scheme、空/无主机名、本机名、字面量私网 IP、IPv4-mapped
IPv6、解析到私网的主机名；多地址中任一为私网即拒绝；`resolve=False` 不发 DNS；
`allow_private` 显式放行开发环境。

- 测试：`TestUrlGuard` 全部 11 个方法

## 运行方式

```bash
# 跑 core 的全部测试
docker exec odoo odoo -c /etc/odoo/odoo.conf -d <db> \
  -i infohub --test-enable --test-tags /infohub \
  --stop-after-init --workers=0 --no-http
```

测试离线可跑（url_guard 用 mock，无网络、无 API key）。

# InfoHub RSS Channel — 验收标准

## AC-1 渠道类型可选

`rss` 出现在 `channel_type` 的 selection 里。 — `test_rss_is_a_selectable_channel_type`

## AC-2 feed 解析

RSS 2.0 基础字段、分类收集、命名空间字段（dc:creator）、Atom 的 alternate link、
RDF 兄弟节点、非法 XML 报 ValueError、空 feed 无条目、Media RSS 的 content 不当正文。

- `TestFeedParsing` 全部 8 个方法

## AC-3 保存期 URL 校验

非 http scheme、字面私网 IP、云元数据地址（169.254.169.254）在保存时就拒绝；
公开 URL 通过；空 URL 允许保存（到抓取时才报）。

- `test_rejects_non_http_feed_url`
- `test_rejects_literal_private_ip`
- `test_rejects_metadata_service_address`
- `test_accepts_public_feed_url`
- `test_blank_url_is_allowed_until_fetch`

## AC-4 抓取

无 URL 时抓取抛 `UrlNotAllowed`；端到端抓取+入库+来源匹配；重抓不重复；失败被
记录且重新抛出；成功清错误状态；簿记失败不掩盖原始错误。

- `test_fetch_without_url_raises`
- `test_fetch_and_ingest_end_to_end`
- `test_refetch_does_not_duplicate`
- `test_fetch_failure_is_recorded_and_reraised`
- `test_register_failure_never_masks_the_cause`
- `test_successful_fetch_clears_error_state`

## 运行方式

```bash
docker exec odoo odoo -c /etc/odoo/odoo.conf -d <db> \
  -i infohub_channel_rss --test-enable --test-tags /infohub_channel_rss \
  --stop-after-init --workers=0 --no-http
```

HTTP 全部 mock，离线可跑。

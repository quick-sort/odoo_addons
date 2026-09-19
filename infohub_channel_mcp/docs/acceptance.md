# InfoHub MCP Channel — 验收标准

## AC-1 结果归一化

解开 result 键、解码 JSON 字符串、透传结构体、忽略非 JSON 文本、None 保持 None。 — `TestResultNormalisation` 前 5 个方法

## AC-2 条目提取

裸列表直接接受；常见信封键（records/items/data/results/news/list/entries）都解开；未知形状与 None 得空。 — `TestResultNormalisation` 后 4 个方法

## AC-3 渠道类型与前置校验

`mcp` 在 selection 中；无 client 或无 tool name 时 fetch 抛 `UserError`。 — `test_mcp_is_a_selectable_channel_type`、`test_channel_without_client_is_rejected_at_fetch`、`test_channel_without_tool_name_is_rejected_at_fetch`

## AC-4 取数与入库

端到端抓取入库；信封键处理；工具字段全保留供过滤；不可解析回复得空；重抓不重复。 — `test_fetch_ingests_items`、`test_envelope_key_is_handled`、`test_every_tool_field_is_preserved_for_filtering`、`test_unparseable_reply_creates_nothing`、`test_refetch_does_not_duplicate`

## AC-5 日期范围与依赖隔离

日期范围传给工具；core 的依赖列表不含 llm。 — `test_date_range_is_passed_to_the_tool`、`test_llm_dependency_is_isolated_to_this_addon`

## 运行方式

```bash
docker exec odoo odoo -c /etc/odoo/odoo.conf -d <db> \
  -i infohub_channel_mcp --test-enable --test-tags /infohub_channel_mcp \
  --stop-after-init --workers=0 --no-http
```

MCP 客户端全部 mock，无网络、无费用。

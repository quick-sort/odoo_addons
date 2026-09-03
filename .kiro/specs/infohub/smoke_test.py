"""InfoHub 冒烟测试脚本。

用法（在容器内跑）::

    docker exec odoo odoo shell -c /etc/odoo/odoo.conf -d test_infohub \
        --no-http --workers=0 < .kiro/specs/infohub/smoke_test.py

覆盖：三轴 component 解析、可解析性约束、采集流水线、同源/跨源去重、
审核与标黑、订阅时间线、portal 越权访问。

不联网：用一个内存里的假 transport 注入 feed 内容，这样测试可重复、不受
外部站点可用性影响。
"""

import logging

logging.disable(logging.WARNING)

FAILED = []
PASSED = []


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
        print(f"  ✓ {name}")
    else:
        FAILED.append(f"{name} {detail}".strip())
        print(f"  ✗ {name} {detail}")


print("=" * 70)
print("InfoHub 冒烟测试")
print("=" * 70)

SMOKE_LOGINS = ["smoke_reader", "smoke_reader2", "smoke_internal"]


def cleanup():
    """清掉历次运行的残留，使脚本可重复执行。

    第 7 节必须提交（独立事务的验证绕不开），而 commit 会把前面几节的数据一并
    落库，所以首尾都要清理。
    """
    Item = env["infohub.item"]
    smoke_sources = env["infohub.source"].with_context(active_test=False).search(
        [("name", "ilike", "冒烟")]
    )
    smoke_items = Item.search([("source_id", "in", smoke_sources.ids)])
    env["infohub.blocklist"].with_context(active_test=False).search(
        ["|", ("item_id", "in", smoke_items.ids), ("reason", "ilike", "冒烟")]
    ).unlink()
    env["infohub.source.run"].search([("source_id", "in", smoke_sources.ids)]).unlink()
    smoke_sources.unlink()
    users = env["res.users"].with_context(active_test=False).search(
        [("login", "in", SMOKE_LOGINS)]
    )
    env["infohub.subscription"].search([("user_id", "in", users.ids)]).unlink()
    users.unlink()
    env["infohub.tag"].with_context(active_test=False).search(
        [("name", "ilike", "冒烟")]
    ).unlink()
    env["infohub.topic"].with_context(active_test=False).search(
        [("code", "=", "smoke_child")]
    ).unlink()
    env.cr.commit()


cleanup()

# ======================================================================
print("\n[1] 三轴组合与可解析性约束（R1.2 / ADR-008）")
# ======================================================================
from odoo.exceptions import AccessError, ValidationError  # noqa: E402

Source = env["infohub.source"]

# 1.1 合法组合：article × rss × generic
source = Source.create(
    {
        "name": "冒烟测试源",
        "medium": "article",
        "transport": "rss",
        "provider": "generic",
        "endpoint": "https://example.com/feed.xml",
    }
)
check("合法组合 (article, rss, generic) 可创建", bool(source.id))

# 1.2 非法组合：core 的 http 传输没有配套的 generic mapper
try:
    Source.create(
        {
            "name": "缺 mapper 的组合",
            "medium": "article",
            "transport": "http",
            "provider": "generic",
            "endpoint": "https://example.com/api",
        }
    )
    check("非法组合被拒绝", False, "(未抛 ValidationError)")
except ValidationError as exc:
    check("非法组合被拒绝", "mapper" in str(exc), f"(提示: {str(exc)[:60]})")

# 1.3 SSRF 防护（N3）。
# 保存时是**不做 DNS 解析**的快速校验（见 url_guard.assert_url_allowed 的 resolve 参数），
# 所以这里全部用字面量 IP、已知本机名或非法 scheme——它们不需要 DNS 就能判定。
for bad_url, label in [
    ("http://127.0.0.1/feed", "环回地址"),
    ("http://169.254.169.254/latest/meta-data/", "云元数据服务"),
    ("http://10.0.0.5/feed", "私网地址"),
    ("http://192.168.1.1/feed", "私网地址（192.168）"),
    ("http://[::1]/feed", "IPv6 环回"),
    ("http://localhost:8069/feed", "localhost"),
    ("http://foo.localhost/feed", "*.localhost"),
    ("file:///etc/passwd", "非 http 协议"),
    ("ftp://example.com/x", "ftp 协议"),
]:
    try:
        Source.create(
            {
                "name": f"SSRF-{label}",
                "medium": "article",
                "transport": "rss",
                "provider": "generic",
                "endpoint": bad_url,
            }
        )
        check(f"SSRF 拦截：{label}", False, "(竟然创建成功)")
    except Exception as exc:  # UserError 的子类
        check(f"SSRF 拦截：{label}", True, f"({type(exc).__name__})")

# ======================================================================
print("\n[2] Component 解析（ADR-001 / ADR-007）")
# ======================================================================
with source.work_on() as work:
    transport = work.component(usage="transport")
    mapper = work.component(usage="mapper")
    medium = work.component(usage="medium")
    http = work.component(usage="http")
    classifiers = work.many_components(usage="classifier")

check("transport 解析为 rss 实现", transport._name == "infohub.transport.rss",
      f"(得到 {transport._name})")
check("mapper 解析为 (generic, rss)", mapper._name == "infohub.mapper.rss",
      f"(得到 {mapper._name})")
check("medium 解析为 article", medium._name == "infohub.medium.article",
      f"(得到 {medium._name})")
check("http 客户端可解析", http._name == "infohub.http")
check("classifier 用 many_components 取到 RSS 归类器",
      any(c._name == "infohub.classifier.rss" for c in classifiers),
      f"(得到 {[c._name for c in classifiers]})")
check("work.source 注入成功", transport.source == source)

# 注册表继承链：infohub.transport.rss 应能取到 infohub.base 的 source 属性
check("component 注册表继承链完整（能取到基类属性）",
      hasattr(transport, "source") and hasattr(transport, "_work_source"))

# ======================================================================
print("\n[3] 采集流水线（R2）")
# ======================================================================
FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>Smoke Feed</title><language>en</language>
  <item>
    <title>First article</title>
    <link>https://example.com/a?utm_source=rss&amp;id=1</link>
    <guid>smoke-guid-1</guid>
    <author>Alice</author>
    <pubDate>Mon, 25 Aug 2026 10:00:00 GMT</pubDate>
    <category>Technology</category>
    <description>&lt;p&gt;Hello &lt;script&gt;alert(1)&lt;/script&gt;world&lt;/p&gt;</description>
  </item>
  <item>
    <title>Second article</title>
    <link>https://example.com/b</link>
    <guid>smoke-guid-2</guid>
    <pubDate>Tue, 26 Aug 2026 10:00:00 GMT</pubDate>
    <description>Short summary</description>
  </item>
</channel></rss>"""


class FakeResponse:
    """够 RssTransport 用的最小响应对象。"""

    status_code = 200
    headers = {"ETag": 'W/"smoke-etag"'}
    url = "https://example.com/feed.xml"

    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        return None


import odoo.addons.infohub.components.http as http_mod  # noqa: E402

_original_get = http_mod.InfohubHttp.get
_calls = {"n": 0}


def fake_get(self, url, **kwargs):
    """第一次返回 feed，第二次模拟 304（验证条件请求短路）。"""
    _calls["n"] += 1
    if kwargs.get("etag") and _calls["n"] > 1:
        return None
    return FakeResponse(FEED)


http_mod.InfohubHttp.get = fake_get
try:
    run = source._fetch()
    items = source.item_ids
    check("抓取产出 2 条条目", len(items) == 2, f"(得到 {len(items)})")
    check("抓取日志记录成功", run.state == "done" and run.item_created == 2,
          f"(state={run.state}, created={run.item_created})")
    check("游标写入 ETag", (source.cursor_state or {}).get("etag") == 'W/"smoke-etag"',
          f"(得到 {source.cursor_state})")

    first = items.filtered(lambda i: i.external_id == "smoke-guid-1")
    check("标题映射正确", first.title == "First article", f"(得到 {first.title!r})")
    check("作者映射正确", first.author_name == "Alice")
    check("发布时间映射正确", bool(first.published_at))
    check("语言从频道级继承", first.lang == "en", f"(得到 {first.lang!r})")
    check("url_host 物化正确", first.url_host == "example.com",
          f"(得到 {first.url_host!r})")

    # XSS 净化（N4）
    body = (first.content or "") + (first.summary or "")
    check("HTML 净化剥掉了 <script>", "<script" not in body.lower(),
          f"(内容: {body[:80]!r})")

    # 跨源去重身份：URL 规范化应剥掉 utm_source
    check("identity_key 使用 GUID", first.identity_key == "smoke-guid-1",
          f"(得到 {first.identity_key!r})")

    # 审核默认发布（R5.2 / ADR-009）
    check("审核默认发布", all(i.state == "published" for i in items),
          f"(状态: {items.mapped('state')})")

    # classifier 把 <category>Technology</category> 映射到学科
    tech = env.ref("infohub.topic_technology")
    check("classifier 归类到「科技」", tech in first.topic_ids,
          f"(得到 {first.topic_ids.mapped('name')})")

    # 3.x 同源去重：再抓一次（这次 304），条目数不变
    before = len(source.item_ids)
    source._fetch()
    check("条件请求命中 304 时不重复入库", len(source.item_ids) == before,
          f"(前 {before}，后 {len(source.item_ids)})")

    # 清掉 etag 强制重新解析，验证 external_id 去重
    source.cursor_state = False
    _calls["n"] = 0
    source._fetch()
    check("同源 external_id 去重生效", len(source.item_ids) == before,
          f"(前 {before}，后 {len(source.item_ids)})")

    # 3.y 跨源去重：另一个源抓同一份 feed，应收敛不新增
    source2 = Source.create(
        {
            "name": "冒烟测试源 2",
            "medium": "article",
            "transport": "rss",
            "provider": "generic",
            "endpoint": "https://example.org/feed.xml",
        }
    )
    _calls["n"] = 0
    source2._fetch()
    check("跨源 identity_key 去重生效（第二个源不新增条目）",
          len(source2.item_ids) == 0, f"(得到 {len(source2.item_ids)})")
finally:
    http_mod.InfohubHttp.get = _original_get

# ======================================================================
print("\n[4] 审核与人工标黑（R5）")
# ======================================================================
target = source.item_ids[0]
target.action_block()
check("单条标黑立即改状态", target.state == "blocked", f"(得到 {target.state})")
check("标黑留痕（生成 blocklist 记录）",
      bool(env["infohub.blocklist"].search_count(
          [("block_type", "=", "item"), ("item_id", "=", target.id)])))

target.action_unblock()
check("撤销标黑恢复发布", target.state == "published")

# 关键词前瞻拦截
env["infohub.blocklist"].create(
    {"block_type": "keyword", "value": "Second", "reason": "冒烟测试"}
)
second = source.item_ids.filtered(lambda i: i.title == "Second article")
second.state = "fetched"
second._moderate()
check("关键词黑名单前瞻拦截新条目", second.state == "blocked",
      f"(得到 {second.state})")

# 域名标黑用 url_host 精确匹配，不应误伤
entry = env["infohub.blocklist"].create(
    {"block_type": "domain", "value": "notexample.com", "reason": "冒烟：误伤测试"}
)
check("域名标黑不误伤相似域名", entry.matched_count == 0,
      f"(命中 {entry.matched_count})")
entry.active = False

# ======================================================================
print("\n[5] 订阅与时间线（R7 / ADR-003）")
# ======================================================================
reader = env["res.users"].create(
    {
        "name": "冒烟读者",
        "login": "smoke_reader",
        "group_ids": [(6, 0, [env.ref("base.group_portal").id,
                              env.ref("infohub.group_reader").id])],
    }
)

sub = env["infohub.subscription"].create(
    {"user_id": reader.id, "target_type": "source", "source_id": source.id}
)
domain = reader._infohub_timeline_domain()
timeline = env["infohub.item"].search(domain)
published = source.item_ids.filtered(lambda i: i.state == "published")
check("按源订阅的时间线命中已发布条目",
      set(timeline.ids) == set(published.ids),
      f"(时间线 {len(timeline)}，已发布 {len(published)})")

# 学科订阅走 child_of：订阅父学科应覆盖子学科
child = env["infohub.topic"].create(
    {"name": "冒烟子学科", "code": "smoke_child",
     "parent_id": env.ref("infohub.topic_technology").id}
)
sub.unlink()
env["infohub.subscription"].create(
    {"user_id": reader.id, "target_type": "topic",
     "topic_id": env.ref("infohub.topic_technology").id}
)
first = source.item_ids.filtered(lambda i: i.external_id == "smoke-guid-1")
first.topic_ids = [(6, 0, [child.id])]
timeline = env["infohub.item"].search(reader._infohub_timeline_domain())
check("学科订阅按 child_of 覆盖子学科", first in timeline,
      f"(时间线: {timeline.mapped('title')})")

# 未读计数与水位线
subs = reader.infohub_subscription_ids
check("未读计数可计算", subs[0].unread_count >= 1,
      f"(得到 {subs[0].unread_count})")
subs[0].action_mark_all_read()
check("水位线推进后未读归零", subs[0].unread_count == 0,
      f"(得到 {subs[0].unread_count})")

# 屏蔽标签
tag = env["infohub.tag"].create({"name": "冒烟屏蔽标签"})
first.tag_ids = [(4, tag.id)]
reader.infohub_muted_tag_ids = [(4, tag.id)]
timeline = env["infohub.item"].search(reader._infohub_timeline_domain())
check("屏蔽标签从时间线剔除条目", first not in timeline)
reader.infohub_muted_tag_ids = [(5, 0, 0)]

# ======================================================================
print("\n[6] 权限与越权（N6 / N7 / ADR-015）")
# ======================================================================
other = env["res.users"].create(
    {
        "name": "另一个读者",
        "login": "smoke_reader2",
        "group_ids": [(6, 0, [env.ref("base.group_portal").id,
                              env.ref("infohub.group_reader").id])],
    }
)
other_sub = env["infohub.subscription"].create(
    {"user_id": other.id, "target_type": "source", "source_id": source.id}
)

reader_env = env["infohub.subscription"].with_user(reader)
visible = reader_env.search([])
check("portal 读者看不到他人的订阅",
      other_sub not in visible and all(s.user_id == reader for s in visible),
      f"(看到 {len(visible)} 条，用户 {visible.mapped('user_id.login')})")

try:
    other_sub.with_user(reader).write({"active": False})
    check("portal 读者无法改他人订阅", False, "(竟然写成功)")
except AccessError:
    check("portal 读者无法改他人订阅", True)

# 凭证对 portal 与普通内部用户完全不可见（N6）
try:
    env["infohub.credential"].with_user(reader).search([])
    check("portal 读者无法访问凭证", False, "(竟然可读)")
except AccessError:
    check("portal 读者无法访问凭证", True)

internal = env["res.users"].create(
    {
        "name": "冒烟内部用户",
        "login": "smoke_internal",
        "group_ids": [(6, 0, [env.ref("base.group_user").id,
                              env.ref("infohub.group_user").id])],
    }
)
try:
    env["infohub.credential"].with_user(internal).search([])
    check("普通内部用户无法访问凭证", False, "(竟然可读)")
except AccessError:
    check("普通内部用户无法访问凭证", True)

# 条目记录规则：读者只见 published + public
blocked_item = source.item_ids.filtered(lambda i: i.state == "blocked")
reader_items = env["infohub.item"].with_user(reader).search([])
check("portal 读者看不到非 published 条目",
      not any(i in reader_items for i in blocked_item),
      f"(标黑条目 {blocked_item.ids} 泄露)")

# internal 源对 portal 不可见
source.access_level = "internal"
reader_items = env["infohub.item"].with_user(reader).search([])
check("access_level=internal 的条目对 portal 不可见", len(reader_items) == 0,
      f"(仍看到 {len(reader_items)} 条)")
source.access_level = "public"

# 内部用户能看到全部
internal_items = env["infohub.item"].with_user(internal).search([])
check("内部用户可见全部条目", len(internal_items) >= len(source.item_ids),
      f"(看到 {len(internal_items)}，实际 {len(source.item_ids)})")

# ======================================================================
print("\n[7] 失败簿记走独立事务（R1.6）")
# ======================================================================
# 这一节必须先提交：_register_failure 在独立 cursor 里写簿记，看不到当前事务
# 里尚未提交的记录（它有 exists() 保护，会直接跳过）。这正是生产行为——源都是
# 已提交的记录——但测试里得显式配合。
fail_source = Source.create(
    {
        "name": "冒烟失败源",
        "medium": "article",
        "transport": "rss",
        "provider": "generic",
        "endpoint": "https://example.com/broken.xml",
        "max_errors": 2,
    }
)
env.cr.commit()
fail_source_id = fail_source.id


def boom(self, url, **kwargs):
    raise RuntimeError("冒烟测试注入的故障")


http_mod.InfohubHttp.get = boom
try:
    for _ in range(2):
        try:
            fail_source._fetch()
        except RuntimeError:
            # 生产中这个异常由 queue_job 接住并回滚事务
            env.cr.rollback()
finally:
    http_mod.InfohubHttp.get = _original_get

# 独立 cursor 已提交，重新读取
fail_source = env["infohub.source"].browse(fail_source_id)
fail_source.invalidate_recordset()
check("失败计数在独立事务中累加成功（回滚后仍存活）",
      fail_source.error_count == 2, f"(得到 {fail_source.error_count})")
check("达到阈值后自动停用", not fail_source.active,
      f"(active={fail_source.active})")
check("失败日志已记录（回滚后仍存活）",
      env["infohub.source.run"].search_count(
          [("source_id", "=", fail_source_id), ("state", "=", "failed")]) == 2)

fail_source.action_reactivate()
check("重新启用清空失败计数",
      fail_source.active and fail_source.error_count == 0)

# 清理这一节提交的数据
env["infohub.source.run"].search([("source_id", "=", fail_source_id)]).unlink()
fail_source.unlink()
env.cr.commit()

# ======================================================================
print("\n" + "=" * 70)
print(f"通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
if FAILED:
    print("\n失败明细：")
    for item in FAILED:
        print(f"  ✗ {item}")
print("=" * 70)

cleanup()
print("（测试数据已清理）")

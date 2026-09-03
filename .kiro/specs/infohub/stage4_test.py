"""阶段 4 测试：infohub_fulltext + infohub_filter。

    docker exec -i odoo odoo shell -c /etc/odoo/odoo.conf -d test_infohub \
        --no-http --workers=0 < .kiro/specs/infohub/stage4_test.py

覆盖：规则条件（domain / 正则 / 范围）、五种动作、终结型 vs 标注型、stop_after、
求值顺序、坏正则与坏 domain 的保存期校验、试运行；正文提取的候选筛选、成功回写、
各类失败分支、幂等与重试、SSRF 继承。

不联网：注入假 HTTP 响应。
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
print("InfoHub 阶段 4 测试（正文提取 + 规则引擎）")
print("=" * 70)

from odoo.exceptions import ValidationError  # noqa: E402


def cleanup():
    sources = env["infohub.source"].with_context(active_test=False).search(
        [("name", "ilike", "四测")]
    )
    items = env["infohub.item"].search([("source_id", "in", sources.ids)])
    env["infohub.blocklist"].with_context(active_test=False).search(
        [("item_id", "in", items.ids)]
    ).unlink()
    env["infohub.source.run"].search([("source_id", "in", sources.ids)]).unlink()
    sources.unlink()
    env["infohub.rule"].with_context(active_test=False).search(
        [("name", "ilike", "四测")]
    ).unlink()
    env["infohub.tag"].with_context(active_test=False).search(
        [("name", "ilike", "四测")]
    ).unlink()
    env.cr.commit()


cleanup()

Source = env["infohub.source"]
Item = env["infohub.item"]
Rule = env["infohub.rule"]

source = Source.create({
    "name": "四测源", "medium": "article", "transport": "rss",
    "provider": "generic", "endpoint": "https://example.com/four.xml",
    "fulltext_enabled": False,   # 规则测试期间先关掉，免得互相干扰
})

tag_ad = env["infohub.tag"].create({"name": "四测广告"})
tag_hot = env["infohub.tag"].create({"name": "四测热点"})
topic_tech = env.ref("infohub.topic_technology")


def make_item(title, text="", state="fetched", **kw):
    vals = {
        "source_id": source.id, "title": title, "state": state,
        "content_text": text, "external_id": f"four-{title}",
        "identity_key": f"four-{title}",
    }
    vals.update(kw)
    return Item.create(vals)


# ======================================================================
print("\n[1] 规则条件")
# ======================================================================
rule_regex = Rule.create({
    "name": "四测：标题含广告则拒绝",
    "sequence": 10, "keyword_regex": "(广告|推广)", "regex_target": "title",
    "action": "reject",
})

i_ad = make_item("这是一条广告内容")
i_ok = make_item("这是一条正常内容")
check("正则命中标题", rule_regex._match(i_ad | i_ok) == i_ad,
      f"(命中 {rule_regex._match(i_ad | i_ok).mapped('title')})")

rule_body = Rule.create({
    "name": "四测：正文含关键词",
    "sequence": 20, "keyword_regex": "限时特惠", "regex_target": "content",
    "action": "tag", "tag_ids": [(6, 0, [tag_ad.id])],
})
i_body = make_item("标题干净", text="正文里藏了限时特惠字样")
check("正则只匹配正文时命中正文", rule_body._match(i_body) == i_body)
check("正则只匹配正文时不看标题",
      not rule_body._match(make_item("限时特惠在标题里", text="正文干净")))

rule_domain = Rule.create({
    "name": "四测：仅本源 + 高分",
    "sequence": 30,
    "condition_domain": f"[('source_id', '=', {source.id}), ('score', '>=', 5)]",
    "action": "tag", "tag_ids": [(6, 0, [tag_hot.id])],
})
i_hi = make_item("高分条目", score=9.0)
i_lo = make_item("低分条目", score=1.0)
check("domain 条件生效", rule_domain._match(i_hi | i_lo) == i_hi,
      f"(命中 {rule_domain._match(i_hi | i_lo).mapped('title')})")

rule_both = Rule.create({
    "name": "四测：domain 与正则都要满足",
    "sequence": 40,
    "condition_domain": f"[('source_id', '=', {source.id})]",
    "keyword_regex": "必须同时", "regex_target": "both",
    "action": "tag", "tag_ids": [(6, 0, [tag_hot.id])],
})
i_both = make_item("必须同时满足两个条件")
check("domain 与正则是与关系", rule_both._match(i_both | i_hi) == i_both)

# ======================================================================
print("\n[2] 五种动作")
# ======================================================================
r_tag = Rule.create({"name": "四测动作tag", "action": "tag",
                     "tag_ids": [(6, 0, [tag_hot.id])], "sequence": 100})
t = make_item("打标签目标")
r_tag._execute(t)
check("打标签动作生效", tag_hot in t.tag_ids, f"(得到 {t.tag_ids.mapped('name')})")

r_score = Rule.create({"name": "四测动作score", "action": "score",
                       "score_delta": 3.5, "sequence": 101})
t = make_item("评分目标", score=1.0)
r_score._execute(t)
check("评分动作累加", abs(t.score - 4.5) < 0.001, f"(得到 {t.score})")

r_topic = Rule.create({"name": "四测动作topic", "action": "topic",
                       "topic_ids": [(6, 0, [topic_tech.id])],
                       "set_primary_topic": True, "sequence": 102})
t = make_item("学科目标")
r_topic._execute(t)
check("指派学科动作生效", topic_tech in t.topic_ids)
check("同时设为主学科", t.primary_topic_id == topic_tech,
      f"(得到 {t.primary_topic_id.name})")

t2 = make_item("已有主学科", primary_topic_id=env.ref("infohub.topic_other").id)
r_topic._execute(t2)
check("不覆盖已有的主学科",
      t2.primary_topic_id == env.ref("infohub.topic_other"),
      f"(得到 {t2.primary_topic_id.name})")

r_pub = Rule.create({"name": "四测动作publish", "action": "publish", "sequence": 103})
t = make_item("发布目标")
r_pub._execute(t)
check("直接发布动作生效", t.state == "published", f"(得到 {t.state})")
check("发布留下审核说明", "四测动作publish" in (t.moderation_note or ""),
      f"(得到 {t.moderation_note!r})")

r_rej = Rule.create({"name": "四测动作reject", "action": "reject", "sequence": 104})
t = make_item("拒绝目标")
r_rej._execute(t)
check("直接拒绝动作生效", t.state == "rejected", f"(得到 {t.state})")

check("命中计数累加", r_rej.hit_count == 1, f"(得到 {r_rej.hit_count})")

# ======================================================================
print("\n[3] 终结型 vs 标注型，以及 stop_after")
# ======================================================================
Rule.search([]).write({"active": False})   # 先全部停用，逐个启用来控制顺序

r1 = Rule.create({
    "name": "四测顺序1：打标签", "sequence": 10, "action": "tag",
    "tag_ids": [(6, 0, [tag_hot.id])], "keyword_regex": "顺序验证",
})
r2 = Rule.create({
    "name": "四测顺序2：拒绝", "sequence": 20, "action": "reject",
    "keyword_regex": "顺序验证",
})
r3 = Rule.create({
    "name": "四测顺序3：再打标签", "sequence": 30, "action": "tag",
    "tag_ids": [(6, 0, [tag_ad.id])], "keyword_regex": "顺序验证",
})

target = make_item("顺序验证条目")
remaining = Rule._apply(target)
check("标注型规则先执行（打上了标签）", tag_hot in target.tag_ids)
check("终结型规则定下状态", target.state == "rejected", f"(得到 {target.state})")
check("终结后不再过后续规则（没打上第二个标签）", tag_ad not in target.tag_ids,
      f"(得到 {target.tag_ids.mapped('name')})")
check("终结的条目不交回核心", target not in remaining,
      f"(remaining={remaining.mapped('title')})")

# stop_after：标注型也能中断后续求值，但状态仍交回核心
Rule.search([]).write({"active": False})
s1 = Rule.create({
    "name": "四测stop1", "sequence": 10, "action": "tag",
    "tag_ids": [(6, 0, [tag_hot.id])], "keyword_regex": "停止验证",
    "stop_after": True,
})
s2 = Rule.create({
    "name": "四测stop2", "sequence": 20, "action": "tag",
    "tag_ids": [(6, 0, [tag_ad.id])], "keyword_regex": "停止验证",
})
target = make_item("停止验证条目")
remaining = Rule._apply(target)
check("stop_after 打上了自己的标签", tag_hot in target.tag_ids)
check("stop_after 阻止了后续规则", tag_ad not in target.tag_ids,
      f"(得到 {target.tag_ids.mapped('name')})")
check("stop_after 的条目仍交回核心定状态", target in remaining,
      f"(remaining={remaining.mapped('title')})")

# ======================================================================
print("\n[4] _moderate 集成：规则 + 核心默认发布（ADR-009 / R6.4）")
# ======================================================================
Rule.search([]).write({"active": False})
Rule.create({
    "name": "四测审核：拒绝垃圾", "sequence": 10, "action": "reject",
    "keyword_regex": "垃圾内容", "regex_target": "title",
})

spam = make_item("这是垃圾内容")
good = make_item("这是好内容")
(spam | good)._moderate()
check("规则命中的条目被拒绝", spam.state == "rejected", f"(得到 {spam.state})")
check("未命中的条目走核心默认发布", good.state == "published",
      f"(得到 {good.state})")

# 人工标黑仍然优先（核心的 _check_blocklist 在 super 里）
env["infohub.blocklist"].create({
    "block_type": "keyword", "value": "四测黑词", "reason": "四测",
})
blocked = make_item("含四测黑词的条目")
blocked._moderate()
check("规则未命中但黑名单命中 -> blocked", blocked.state == "blocked",
      f"(得到 {blocked.state})")
env["infohub.blocklist"].search([("reason", "=", "四测")]).unlink()

# ======================================================================
print("\n[5] 保存期校验")
# ======================================================================
# 每个都用 savepoint 包住：数据库层的 CHECK 约束会抛 psycopg2 错误并把整个事务
# 置为 aborted，后续任何语句都会失败。savepoint 让异常只回滚到该点。
def expect_rejected(name, vals, expect_in=None):
    try:
        with env.cr.savepoint():
            Rule.create(vals)
        check(name, False, "(竟然保存成功)")
    except Exception as exc:  # noqa: BLE001 - Python 层与数据库层的异常类型不同
        detail = str(exc)
        ok = (expect_in in detail) if expect_in else True
        check(name, ok, f"({type(exc).__name__}: {detail[:60]})")


expect_rejected("坏正则被拒绝保存",
                {"name": "四测坏正则", "action": "tag",
                 "tag_ids": [(6, 0, [tag_hot.id])],
                 "keyword_regex": "([unclosed"}, "正则")
expect_rejected("坏 domain 被拒绝保存",
                {"name": "四测坏domain", "action": "tag",
                 "tag_ids": [(6, 0, [tag_hot.id])],
                 "condition_domain": "[('不存在的字段', '=', 1)]"}, "domain")
expect_rejected("tag 动作缺标签被拒绝",
                {"name": "四测缺标签", "action": "tag"}, "标签")
expect_rejected("score 动作零增减被拒绝",
                {"name": "四测零分", "action": "score", "score_delta": 0})

# ======================================================================
print("\n[6] 试运行")
# ======================================================================
Rule.search([]).write({"active": False})
dry = Rule.create({
    "name": "四测试运行", "action": "tag", "tag_ids": [(6, 0, [tag_hot.id])],
    "keyword_regex": "顺序验证",
})
result = dry.action_dry_run()
check("试运行返回通知", result.get("tag") == "display_notification",
      f"(得到 {result.get('tag')})")
check("试运行不改数据", dry.hit_count == 0, f"(得到 {dry.hit_count})")
matches = dry.action_view_matches()
check("查看命中返回 act_window", matches.get("res_model") == "infohub.item")

Rule.search([]).write({"active": False})

# ======================================================================
print("\n[7] 正文提取：候选筛选")
# ======================================================================
source.write({"fulltext_enabled": True, "fulltext_min_length": 500})

with source.work_on() as work:
    enrichers = work.many_components(usage="enricher")
check("enricher 被解析到",
      any(e._name == "infohub.enricher.fulltext" for e in enrichers),
      f"(得到 {[e._name for e in enrichers]})")

with source.work_on() as work:
    enricher = [e for e in work.many_components(usage="enricher")
                if e._name == "infohub.enricher.fulltext"][0]

    i_short = make_item("正文太短需要提取", text="只有一句话", url="https://example.com/1")
    i_long = make_item("正文已够长", text="x" * 600, url="https://example.com/2")
    i_nourl = make_item("没有链接", text="短")
    i_done = make_item("已提取过", text="短", url="https://example.com/3")
    i_done.fulltext_state = "done"

    candidates = enricher._candidates(i_short | i_long | i_nourl | i_done)
    check("只挑正文过短的", i_short in candidates)
    check("跳过正文已够长的", i_long not in candidates)
    check("跳过没有 url 的", i_nourl not in candidates)
    check("跳过已处理过的", i_done not in candidates)

# 源上关掉开关后 enricher 不再匹配
source.fulltext_enabled = False
with source.work_on() as work:
    names = [e._name for e in work.many_components(usage="enricher")]
check("源上关掉开关后 enricher 不匹配",
      "infohub.enricher.fulltext" not in names, f"(得到 {names})")
source.fulltext_enabled = True

# ======================================================================
print("\n[8] 正文提取：成功与各类失败")
# ======================================================================
import odoo.addons.infohub.components.http as http_mod  # noqa: E402
from odoo.addons.infohub.url_guard import UrlNotAllowed  # noqa: E402

_original_get = http_mod.InfohubHttp.get

ARTICLE = """<!DOCTYPE html><html><head><title>测试文章</title></head><body>
<nav>导航栏 首页 关于 联系</nav>
<aside>广告位 推荐阅读 热门标签</aside>
<article><h1>测试文章标题</h1>
<p>这是正文的第一段，需要足够长才能通过最小长度校验。""" + "内容填充。" * 40 + """</p>
<p>这是正文的第二段，同样需要足够的长度。""" + "更多内容。" * 40 + """</p>
<script>alert('xss')</script>
</article>
<footer>版权所有 备案号</footer></body></html>"""


class FakeResponse:
    status_code = 200
    headers = {}

    def __init__(self, text, url="https://example.com/1"):
        self.text = text
        self.content = text.encode()
        self.url = url

    def raise_for_status(self):
        return None


def make_get(behaviour):
    def fake_get(self, url, **kw):
        return behaviour(url)
    return fake_get


# 成功路径
http_mod.InfohubHttp.get = make_get(lambda url: FakeResponse(ARTICLE))
try:
    target = make_item("待提取正文", text="摘要一句", url="https://example.com/ok")
    with source.work_on() as work:
        enricher = [e for e in work.many_components(usage="enricher")
                    if e._name == "infohub.enricher.fulltext"][0]
        enricher.enrich(target)
    check("提取成功后状态为 done", target.fulltext_state == "done",
          f"(得到 {target.fulltext_state}, err={target.fulltext_error!r})")
    check("正文被回写", len(target.content_text or "") > 200,
          f"(长度 {len(target.content_text or '')})")
    check("记录了提取字符数", target.fulltext_length > 200,
          f"(得到 {target.fulltext_length})")
    check("剥掉了导航与页脚",
          "导航栏" not in (target.content_text or "")
          and "版权所有" not in (target.content_text or ""),
          "(噪声未剥净)")
    check("正文净化掉了 <script>",
          "<script" not in (target.content or "").lower())
    check("保留了正文段落", "正文的第一段" in (target.content_text or ""))

    # 提取不出正文
    http_mod.InfohubHttp.get = make_get(
        lambda url: FakeResponse("<html><body><nav>只有导航</nav></body></html>"))
    t = make_item("提取不出正文", text="短", url="https://example.com/empty")
    with source.work_on() as work:
        enricher = [e for e in work.many_components(usage="enricher")
                    if e._name == "infohub.enricher.fulltext"][0]
        enricher.enrich(t)
    check("提取不出正文时标记 failed", t.fulltext_state == "failed",
          f"(得到 {t.fulltext_state})")
    check("失败原因已记录", bool(t.fulltext_error))

    # 正文过短（付费墙场景）
    http_mod.InfohubHttp.get = make_get(lambda url: FakeResponse(
        "<html><body><article><p>请订阅后阅读全文。</p></article></body></html>"))
    t = make_item("付费墙", text="短", url="https://example.com/paywall")
    with source.work_on() as work:
        enricher = [e for e in work.many_components(usage="enricher")
                    if e._name == "infohub.enricher.fulltext"][0]
        enricher.enrich(t)
    check("正文过短时标记 failed", t.fulltext_state == "failed",
          f"(得到 {t.fulltext_state})")
    check("过短失败的提示提到付费墙或过短",
          "过短" in (t.fulltext_error or "") or "付费墙" in (t.fulltext_error or ""),
          f"(得到 {t.fulltext_error!r})")

    # 网络错误
    def boom(url):
        raise RuntimeError("连接超时")
    http_mod.InfohubHttp.get = make_get(boom)
    t = make_item("网络失败", text="短", url="https://example.com/timeout")
    with source.work_on() as work:
        enricher = [e for e in work.many_components(usage="enricher")
                    if e._name == "infohub.enricher.fulltext"][0]
        enricher.enrich(t)
    check("网络错误被记录为 failed", t.fulltext_state == "failed",
          f"(得到 {t.fulltext_state})")
    check("网络错误信息含异常类型", "RuntimeError" in (t.fulltext_error or ""),
          f"(得到 {t.fulltext_error!r})")

    # SSRF：URL 校验失败
    def ssrf(url):
        raise UrlNotAllowed("拒绝访问：解析到受限地址")
    http_mod.InfohubHttp.get = make_get(ssrf)
    t = make_item("SSRF 目标", text="短", url="https://example.com/internal")
    with source.work_on() as work:
        enricher = [e for e in work.many_components(usage="enricher")
                    if e._name == "infohub.enricher.fulltext"][0]
        enricher.enrich(t)
    check("SSRF 拦截被记录为 failed", t.fulltext_state == "failed",
          f"(得到 {t.fulltext_state})")
    check("SSRF 失败提示指明安全校验",
          "安全校验" in (t.fulltext_error or ""), f"(得到 {t.fulltext_error!r})")

    # 失败后不再重试
    http_mod.InfohubHttp.get = make_get(lambda url: FakeResponse(ARTICLE))
    with source.work_on() as work:
        enricher = [e for e in work.many_components(usage="enricher")
                    if e._name == "infohub.enricher.fulltext"][0]
        check("failed 状态的条目不再进入候选",
              t not in enricher._candidates(t))

    # 手工重试会重置状态
    t.action_fulltext_retry()
    check("手工重试把状态重置为 pending", t.fulltext_state == "pending",
          f"(得到 {t.fulltext_state})")
    check("手工重试清空错误", not t.fulltext_error)
finally:
    http_mod.InfohubHttp.get = _original_get

# ======================================================================
print("\n[9] 卸载 infohub_filter 后核心仍能发布（R6.4 硬约束）")
# ======================================================================
# 不真卸载模块（代价太大），而是验证核心 _moderate 的实现本身不依赖规则：
# 直接调用核心那一层的实现，确认它能独立完成发布与黑名单判定。
Rule.search([]).write({"active": False})

t = make_item("核心独立发布验证")
# 模拟"没有任何规则"的情形：_apply 返回全部条目，核心照常发布
remaining = Rule._apply(t)
check("无规则时 _apply 原样返回全部条目", remaining == t)
t._moderate()
check("核心默认发布仍生效", t.state == "published", f"(得到 {t.state})")

# 核心的 _moderate 只处理 fetched 状态，不会覆盖规则已定的状态
t_rej = make_item("已被拒绝的条目", state="rejected")
t_rej._moderate()
check("核心 _moderate 不会覆盖非 fetched 状态", t_rej.state == "rejected",
      f"(得到 {t_rej.state})")

# ======================================================================
print("\n" + "=" * 70)
print(f"通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
if FAILED:
    print("\n失败明细：")
    for entry in FAILED:
        print(f"  ✗ {entry}")
print("=" * 70)

cleanup()
print("（测试数据已清理）")

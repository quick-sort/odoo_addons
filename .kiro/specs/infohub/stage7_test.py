"""阶段 7 测试：infohub_digest + infohub_llm。

    docker exec -i odoo odoo shell -c /etc/odoo/odoo.conf -d test_infohub \
        --no-http --workers=0 < .kiro/specs/infohub/stage7_test.py

覆盖：摘要的内容筛选（订阅周期 / 未读 / 屏蔽标签 / 语言）、按 (用户,周期) 分组、
幂等（already_sent）、无内容跳过、无邮箱失败、邮件渲染；LLM 客户端的一次性提问姿势、
error 键与异常两条失败路径、摘要与翻译、零样本归类的事后校验、成本闸门。

**不产生真实 LLM 费用**：全部 chat 调用被替换成假实现。
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
print("InfoHub 阶段 7 测试（摘要推送 + LLM 增强）")
print("=" * 70)

from odoo import fields  # noqa: E402

LOGINS = ["seven_daily", "seven_weekly", "seven_noemail", "seven_muted"]


def cleanup():
    sources = env["infohub.source"].with_context(active_test=False).search(
        [("name", "ilike", "七测")]
    )
    items = env["infohub.item"].search([("source_id", "in", sources.ids)])
    env["infohub.paper"].search([("item_id", "in", items.ids)]).unlink()
    env["infohub.source.run"].search([("source_id", "in", sources.ids)]).unlink()
    sources.unlink()
    users = env["res.users"].with_context(active_test=False).search(
        [("login", "in", LOGINS)]
    )
    env["infohub.digest.log"].search([("user_id", "in", users.ids)]).unlink()
    env["infohub.subscription"].search([("user_id", "in", users.ids)]).unlink()
    users.unlink()
    env["infohub.tag"].with_context(active_test=False).search(
        [("name", "ilike", "七测")]
    ).unlink()
    env.cr.commit()


cleanup()

Source = env["infohub.source"]
Item = env["infohub.item"]
Log = env["infohub.digest.log"]
Sub = env["infohub.subscription"]

source = Source.create({
    "name": "七测源", "medium": "article", "transport": "rss",
    "provider": "generic", "endpoint": "https://example.com/seven.xml",
})

now = fields.Datetime.now()
recent = fields.Datetime.subtract(now, hours=2)
old = fields.Datetime.subtract(now, days=30)

tag_muted = env["infohub.tag"].create({"name": "七测屏蔽"})


def make_item(title, published=None, state="published", **kw):
    vals = {
        "source_id": source.id, "title": title, "state": state,
        "external_id": f"seven-{title}", "identity_key": f"seven-{title}",
        "published_at": published or recent,
        "summary": f"<p>{title} 的摘要</p>",
    }
    vals.update(kw)
    return Item.create(vals)


i_new1 = make_item("七测新条目一", score=5.0)
i_new2 = make_item("七测新条目二", score=1.0)
i_old = make_item("七测旧条目", published=old)
i_draft = make_item("七测未发布", state="fetched")
i_muted = make_item("七测带屏蔽标签", tag_ids=[(6, 0, [tag_muted.id])])

portal = env.ref("base.group_portal")
reader = env.ref("infohub.group_reader")


def make_user(login, email="x@example.com", frequency="daily"):
    user = env["res.users"].create({
        "name": login, "login": login, "email": email,
        "group_ids": [(6, 0, [portal.id, reader.id])],
    })
    Sub.create({
        "user_id": user.id, "target_type": "source", "source_id": source.id,
        "digest_frequency": frequency,
    })
    return user


u_daily = make_user("seven_daily", "daily@example.com", "daily")
u_weekly = make_user("seven_weekly", "weekly@example.com", "weekly")
u_noemail = make_user("seven_noemail", False, "daily")
u_muted = make_user("seven_muted", "muted@example.com", "daily")
u_muted.infohub_muted_tag_ids = [(4, tag_muted.id)]

# ======================================================================
print("\n[1] 摘要内容筛选")
# ======================================================================
since = Log.period_start("daily", now)
items, total = u_daily._infohub_digest_items("daily", since)
titles = set(items.mapped("title"))

check("包含本周期内发布的新条目",
      {"七测新条目一", "七测新条目二"} <= titles, f"(得到 {titles})")
check("排除周期外的旧条目", "七测旧条目" not in titles)
check("排除未发布条目", "七测未发布" not in titles)
check("按评分降序排列", items[0].title == "七测新条目一",
      f"(得到 {items.mapped('title')})")
check("总数正确", total == len(items), f"(total={total}, len={len(items)})")

muted_items, _t = u_muted._infohub_digest_items("daily", since)
check("屏蔽标签的条目被剔除",
      "七测带屏蔽标签" not in muted_items.mapped("title"),
      f"(得到 {muted_items.mapped('title')})")

# 已读的不进摘要
env["infohub.item.read"].create({
    "user_id": u_daily.id, "item_id": i_new2.id, "is_read": True,
})
items2, _t = u_daily._infohub_digest_items("daily", since)
check("已读条目被剔除", "七测新条目二" not in items2.mapped("title"),
      f"(得到 {items2.mapped('title')})")

# 周期不匹配的订阅不计入
weekly_items, _t = u_daily._infohub_digest_items("weekly", Log.period_start("weekly", now))
check("周期不匹配的订阅不计入（每日用户查每周为空）", not weekly_items,
      f"(得到 {weekly_items.mapped('title')})")

# 语言偏好
u_daily.infohub_lang_filter = "ja"
lang_items, _t = u_daily._infohub_digest_items("daily", since)
check("语言偏好生效（条目 lang 为空仍保留）", bool(lang_items),
      "(语言未知的条目被误剔除)")
i_new1.lang = "en"
lang_items, _t = u_daily._infohub_digest_items("daily", since)
check("语言不匹配的条目被剔除",
      "七测新条目一" not in lang_items.mapped("title"),
      f"(得到 {lang_items.mapped('title')})")
u_daily.infohub_lang_filter = False
i_new1.lang = False

# ======================================================================
print("\n[2] 发送与幂等")
# ======================================================================
log1 = u_daily._infohub_send_digest("daily")
check("发送产生了记录", len(log1) == 1, f"(得到 {len(log1)})")
check("状态为已发送", log1.state == "sent", f"(得到 {log1.state})")
check("记录了条目数", log1.item_count >= 1, f"(得到 {log1.item_count})")
check("关联了邮件记录", bool(log1.mail_id))
check("邮件收件人正确", log1.mail_id.email_to == "daily@example.com",
      f"(得到 {log1.mail_id.email_to})")
check("邮件主题含条目数", "条" in (log1.mail_id.subject or ""),
      f"(得到 {log1.mail_id.subject!r})")

body = log1.mail_id.body_html or ""
check("邮件正文含条目标题", "七测新条目" in body)
check("邮件正文含来源名", "七测源" in body)
check("邮件正文含订阅管理链接", "/infohub/subscriptions" in body)
check("邮件正文用内联样式（邮件客户端兼容）", "style=" in body)

check("already_sent 判定为已发送", Log.already_sent(u_daily, "daily"))
log2 = u_daily._infohub_send_digest("daily")
check("★ 同周期内不重复发送", len(log2) == 0, f"(又发了 {len(log2)} 封)")

# 无内容 -> skipped，且也算已处理
log3 = u_weekly._infohub_send_digest("weekly")
check("每周用户也能收到", log3.state == "sent", f"(得到 {log3.state})")

u_empty = make_user("seven_empty_x", "empty@example.com", "daily")
Sub.search([("user_id", "=", u_empty.id)]).write({"digest_frequency": "daily"})
# 把这个用户的订阅指向一个没有条目的源
empty_source = Source.create({
    "name": "七测空源", "medium": "article", "transport": "rss",
    "provider": "generic", "endpoint": "https://example.com/empty.xml",
})
Sub.search([("user_id", "=", u_empty.id)]).write({"source_id": empty_source.id})
log4 = u_empty._infohub_send_digest("daily")
check("无内容时记为 skipped", log4.state == "skipped", f"(得到 {log4.state})")
check("skipped 也算已处理（不会每轮重算）",
      Log.already_sent(u_empty, "daily"))

# 无邮箱 -> failed
log5 = u_noemail._infohub_send_digest("daily")
check("无邮箱记为 failed", log5.state == "failed", f"(得到 {log5.state})")
check("failed 不算已处理（留给下轮重试）",
      not Log.already_sent(u_noemail, "daily"))

# ======================================================================
print("\n[3] cron 入口")
# ======================================================================
Log.search([]).unlink()
count = env["res.users"]._cron_infohub_send_digests()
check("cron 处理了多个用户", count >= 2, f"(得到 {count})")
daily_logs = Log.search([("frequency", "=", "daily")])
weekly_logs = Log.search([("frequency", "=", "weekly")])
check("每日与每周分别发送", bool(daily_logs) and bool(weekly_logs),
      f"(daily={len(daily_logs)}, weekly={len(weekly_logs)})")
check("★ 一个用户一个周期只有一条记录",
      len(Log.search([("user_id", "=", u_daily.id), ("frequency", "=", "daily")])) == 1)

count2 = env["res.users"]._cron_infohub_send_digests()
check("cron 重跑不重复发送（重跑安全）", count2 == 0, f"(又发了 {count2})")

# ======================================================================
print("\n[4] LLM 客户端：一次性提问的姿势")
# ======================================================================
import odoo.addons.infohub_llm.llm_client as client  # noqa: E402
from odoo.addons.infohub_llm.llm_client import LlmCallFailed  # noqa: E402

# 造一个假的 llm.provider + llm.model。service 字段在基础模块里是空 selection，
# 所以直接建记录会因为 required 失败——用 sudo + 绕过校验的最小方式：
# 检查是否已有可用模型，没有就跳过真实模型部分，只测客户端逻辑
Model = env["llm.model"].sudo()
existing_model = Model.search(
    [("model_use", "in", ["chat", "multimodal"]), ("active", "=", True)], limit=1)

if existing_model:
    check("环境里有可用的 chat 模型", True, "")
    fake_model = existing_model
else:
    print("  ! 环境里没有配置 llm.provider/llm.model，用桩对象测客户端逻辑")
    fake_model = None

# 用桩对象验证 chat() 的调用姿势：断言它传的是空 mail.message 记录集 + prepend_messages
captured = {}


class StubProvider:
    def sudo(self):
        return self

    @staticmethod
    def _extract_content_text(raw):
        if isinstance(raw, list):
            return "".join(part.get("text", "") for part in raw)
        return raw


class StubModel:
    def __init__(self, response):
        self._response = response
        self.env = env
        self.provider_id = StubProvider()

    def sudo(self):
        return self

    def chat(self, messages, **kwargs):
        captured["messages"] = messages
        captured["kwargs"] = kwargs
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


text = client.chat(StubModel({"content": "  这是摘要。  "}), "系统提示", "用户内容" * 10)
check("返回内容已去空白", text == "这是摘要。", f"(得到 {text!r})")
check("★ messages 传的是空 mail.message 记录集",
      captured["messages"]._name == "mail.message" and not captured["messages"],
      f"(得到 {captured['messages']!r})")
check("★ system 与 user 通过 prepend_messages 传入",
      [m["role"] for m in captured["kwargs"]["prepend_messages"]] == ["system", "user"],
      f"(得到 {captured['kwargs'].get('prepend_messages')})")
check("stream 显式为 False", captured["kwargs"]["stream"] is False)
check("显式传了 timeout（llm 模块自身不设超时）",
      captured["kwargs"].get("timeout") == client.DEFAULT_TIMEOUT,
      f"(得到 {captured['kwargs'].get('timeout')})")

# 多段 content 形式
text = client.chat(
    StubModel({"content": [{"type": "text", "text": "多段"},
                           {"type": "text", "text": "内容"}]}),
    "s", "u" * 500)
check("多段 content 被拼成字符串", text == "多段内容", f"(得到 {text!r})")

# 两条失败路径
try:
    client.chat(StubModel({"error": "上游返回 429"}), "s", "u" * 500)
    check("★ error 键被识别为失败", False, "(竟然没抛)")
except LlmCallFailed as exc:
    check("★ error 键被识别为失败", "429" in str(exc), f"(得到 {exc})")

try:
    client.chat(StubModel(RuntimeError("连接失败")), "s", "u" * 500)
    check("异常被收敛成 LlmCallFailed", False, "(竟然没抛 LlmCallFailed)")
except LlmCallFailed as exc:
    check("异常被收敛成 LlmCallFailed", "RuntimeError" in str(exc), f"(得到 {exc})")

try:
    client.chat(StubModel({"content": "   "}), "s", "u" * 500)
    check("空返回被识别为失败", False, "(竟然没抛)")
except LlmCallFailed:
    check("空返回被识别为失败", True)

try:
    client.chat(StubModel({"content": "x"}), "s", "")
    check("空输入被拒绝", False, "(竟然没抛)")
except LlmCallFailed:
    check("空输入被拒绝", True)

# 输入截断
long_input = "字" * 50_000
client.chat(StubModel({"content": "ok"}), "s", long_input, max_input_chars=1000)
sent = captured["kwargs"]["prepend_messages"][1]["content"]
check("★ 超长输入被截断（省钱且避免超上下文）", len(sent) == 1000,
      f"(得到 {len(sent)})")

# ======================================================================
print("\n[5] LLM enricher：摘要与翻译")
# ======================================================================
llm_source = Source.create({
    "name": "七测LLM源", "medium": "article", "transport": "rss",
    "provider": "generic", "endpoint": "https://example.com/llm.xml",
    "llm_summarize": True, "llm_translate_to": "中文",
})

check("源上的 LLM 开关默认全关",
      not source.llm_summarize and not source.llm_translate_to
      and not source.llm_classify)
check("_llm_enabled 正确反映开关", llm_source._llm_enabled()
      and not source._llm_enabled())

with llm_source.work_on() as work:
    names = [e._name for e in work.many_components(usage="enricher")]
check("LLM enricher 在开关打开时被解析到",
      "infohub.enricher.llm" in names, f"(得到 {names})")

with source.work_on() as work:
    names_off = [e._name for e in work.many_components(usage="enricher")]
check("开关关闭时 LLM enricher 不匹配",
      "infohub.enricher.llm" not in names_off, f"(得到 {names_off})")

# mock 掉 client.chat 与 resolve_model，验证 enricher 逻辑
import odoo.addons.infohub_llm.components.enricher as enricher_mod  # noqa: E402

_calls = []


def fake_chat(model, system, user, **kw):
    _calls.append({"system": system, "user": user, "kw": kw})
    if "翻译" in system:
        return f"[译] {user[:20]}"
    return "这是一段生成的摘要。"


_orig_chat = enricher_mod.chat
_orig_resolve = enricher_mod.resolve_model
enricher_mod.chat = fake_chat
enricher_mod.resolve_model = lambda env_, model=None, **kw: StubModel({})

try:
    long_item = Item.create({
        "source_id": llm_source.id, "title": "七测长文条目",
        "external_id": "seven-long", "identity_key": "seven-long",
        "content_text": "正文内容。" * 200, "state": "published",
    })
    short_item = Item.create({
        "source_id": llm_source.id, "title": "七测短文条目",
        "external_id": "seven-short", "identity_key": "seven-short",
        "content_text": "很短。", "state": "published",
    })

    with llm_source.work_on() as work:
        enricher = [e for e in work.many_components(usage="enricher")
                    if e._name == "infohub.enricher.llm"][0]
        enricher.enrich(long_item | short_item)

    check("生成了 LLM 摘要", long_item.llm_summary == "这是一段生成的摘要。",
          f"(得到 {long_item.llm_summary!r})")
    check("★ LLM 摘要不覆盖原摘要", not long_item.summary or
          "生成的摘要" not in str(long_item.summary))
    check("生成了译文标题", bool(long_item.llm_translated_title),
          f"(得到 {long_item.llm_translated_title!r})")
    check("生成了译文摘要", bool(long_item.llm_translated_summary))
    check("★ 译文摘要基于 LLM 摘要而非原摘要（更短更省）",
          any("生成的摘要" in call["user"] for call in _calls),
          f"(全部调用的输入：{[c['user'][:25] for c in _calls]})")
    check("状态标为已处理", long_item.llm_state == "done",
          f"(得到 {long_item.llm_state})")

    check("★ 短文不做摘要（压缩没意义，省钱）", not short_item.llm_summary,
          f"(得到 {short_item.llm_summary!r})")
    check("短文仍做了翻译", bool(short_item.llm_translated_title))

    # 已处理的不重复调用
    before = len(_calls)
    with llm_source.work_on() as work:
        enricher = [e for e in work.many_components(usage="enricher")
                    if e._name == "infohub.enricher.llm"][0]
        enricher.enrich(long_item | short_item)
    check("★ 已处理的条目不重复调用（避免重复花钱）", len(_calls) == before,
          f"(又调用了 {len(_calls) - before} 次)")

    # 手工重试会重置
    long_item.action_llm_retry()
    check("手工重试重置为 pending", long_item.llm_state == "pending")

    # 全部失败 -> failed
    def failing_chat(model, system, user, **kw):
        raise LlmCallFailed("模拟失败")

    enricher_mod.chat = failing_chat
    fail_item = Item.create({
        "source_id": llm_source.id, "title": "七测失败条目",
        "external_id": "seven-fail", "identity_key": "seven-fail",
        "content_text": "正文内容。" * 200, "state": "published",
    })
    with llm_source.work_on() as work:
        enricher = [e for e in work.many_components(usage="enricher")
                    if e._name == "infohub.enricher.llm"][0]
        enricher.enrich(fail_item)
    check("全部失败时标为 failed", fail_item.llm_state == "failed",
          f"(得到 {fail_item.llm_state})")
    check("失败原因已记录", "模拟失败" in (fail_item.llm_error or ""),
          f"(得到 {fail_item.llm_error!r})")

    # 没配模型时不炸
    enricher_mod.resolve_model = lambda env_, model=None, **kw: (_ for _ in ()).throw(
        Exception("没有可用模型"))
    no_model_item = Item.create({
        "source_id": llm_source.id, "title": "七测无模型",
        "external_id": "seven-nomodel", "identity_key": "seven-nomodel",
        "content_text": "正文。" * 200, "state": "published",
    })
    with llm_source.work_on() as work:
        enricher = [e for e in work.many_components(usage="enricher")
                    if e._name == "infohub.enricher.llm"][0]
        result = enricher.enrich(no_model_item)
    check("没配模型时优雅跳过而不是抛异常", result is False,
          f"(得到 {result})")
    check("没配模型时条目仍是 pending（下次可重试）",
          no_model_item.llm_state == "pending", f"(得到 {no_model_item.llm_state})")
finally:
    enricher_mod.chat = _orig_chat
    enricher_mod.resolve_model = _orig_resolve

# ======================================================================
print("\n[6] LLM classifier：零样本归类与事后校验")
# ======================================================================
import odoo.addons.infohub_llm.components.classifier as cls_mod  # noqa: E402

cls_source = Source.create({
    "name": "七测归类源", "medium": "article", "transport": "rss",
    "provider": "generic", "endpoint": "https://example.com/cls.xml",
    "llm_classify": True,
})

with cls_source.work_on() as work:
    cls_names = [c._name for c in work.many_components(usage="classifier")]
check("LLM classifier 在开关打开时被解析到",
      "infohub.classifier.llm" in cls_names, f"(得到 {cls_names})")

with source.work_on() as work:
    cls_off = [c._name for c in work.many_components(usage="classifier")]
check("开关关闭时 LLM classifier 不匹配",
      "infohub.classifier.llm" not in cls_off, f"(得到 {cls_off})")

_orig_cls_chat = cls_mod.chat
_orig_cls_resolve = cls_mod.resolve_model
cls_mod.resolve_model = lambda env_, model=None, **kw: StubModel({})

try:
    def make_cls_item(title):
        return Item.create({
            "source_id": cls_source.id, "title": title,
            "external_id": f"seven-cls-{title}", "identity_key": f"seven-cls-{title}",
            "content_text": "内容。" * 50, "state": "published",
        })

    # 合法回答
    cls_mod.chat = lambda m, s, u, **kw: "technology"
    it = make_cls_item("合法回答")
    with cls_source.work_on() as work:
        clf = [c for c in work.many_components(usage="classifier")
               if c._name == "infohub.classifier.llm"][0]
        ok = clf.classify(it, {})
    check("合法编码被采用", ok and env.ref("infohub.topic_technology") in it.topic_ids,
          f"(得到 {it.topic_ids.mapped('code')})")
    check("主学科被设置", it.primary_topic_id.code == "technology",
          f"(得到 {it.primary_topic_id.code})")

    # 带解释的回答 -> 仍能从中提取编码
    cls_mod.chat = lambda m, s, u, **kw: "我认为这属于 technology 这个学科。"
    it2 = make_cls_item("带解释")
    with cls_source.work_on() as work:
        clf = [c for c in work.many_components(usage="classifier")
               if c._name == "infohub.classifier.llm"][0]
        ok2 = clf.classify(it2, {})
    check("★ 带解释的回答仍能提取出编码", ok2, "(没能提取)")

    # 不存在的编码 -> 必须拒绝
    cls_mod.chat = lambda m, s, u, **kw: "quantum-astrology"
    it3 = make_cls_item("编造编码")
    with cls_source.work_on() as work:
        clf = [c for c in work.many_components(usage="classifier")
               if c._name == "infohub.classifier.llm"][0]
        ok3 = clf.classify(it3, {})
    check("★ 不存在的编码被拒绝（事后校验是必需的）",
          ok3 is False and not it3.topic_ids,
          f"(得到 {it3.topic_ids.mapped('code')})")

    # NONE -> 不归类
    cls_mod.chat = lambda m, s, u, **kw: "NONE"
    it4 = make_cls_item("拒答")
    with cls_source.work_on() as work:
        clf = [c for c in work.many_components(usage="classifier")
               if c._name == "infohub.classifier.llm"][0]
        ok4 = clf.classify(it4, {})
    check("NONE 被识别为不归类", ok4 is False and not it4.topic_ids)

    # 调用失败 -> 不炸
    def cls_fail(m, s, u, **kw):
        raise LlmCallFailed("模拟归类失败")

    cls_mod.chat = cls_fail
    it5 = make_cls_item("调用失败")
    with cls_source.work_on() as work:
        clf = [c for c in work.many_components(usage="classifier")
               if c._name == "infohub.classifier.llm"][0]
        ok5 = clf.classify(it5, {})
    check("归类调用失败时优雅返回 False", ok5 is False)

    # 候选集有上限
    with cls_source.work_on() as work:
        clf = [c for c in work.many_components(usage="classifier")
               if c._name == "infohub.classifier.llm"][0]
        candidates = clf._candidates()
    check("候选学科有数量上限（提示不会无限长）",
          len(candidates) <= cls_mod.MAX_CANDIDATES,
          f"(得到 {len(candidates)}，上限 {cls_mod.MAX_CANDIDATES})")
    check("候选只取层级浅的学科",
          all((t.parent_path or "").count("/") <= 2 for t in candidates),
          "(取到了过深的学科)")
finally:
    cls_mod.chat = _orig_cls_chat
    cls_mod.resolve_model = _orig_cls_resolve

# ======================================================================
print("\n" + "=" * 70)
print(f"通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
if FAILED:
    print("\n失败明细：")
    for entry in FAILED:
        print(f"  ✗ {entry}")
print("=" * 70)

env["res.users"].with_context(active_test=False).search(
    [("login", "=", "seven_empty_x")]
).unlink()
cleanup()
print("（测试数据已清理，未产生任何真实 LLM 调用）")

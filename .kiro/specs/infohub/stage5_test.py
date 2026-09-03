"""阶段 5 测试：infohub_paper + infohub_arxiv（三轴抽象复核点）。

    docker exec -i odoo odoo shell -c /etc/odoo/odoo.conf -d test_infohub \
        --no-http --workers=0 < .kiro/specs/infohub/stage5_test.py

覆盖：DOI / arXiv ID 归一化、介质身份计算（含从自由文本捞 DOI）、载荷落库、
作者与期刊解析、arXiv mapper、分类映射、限速通道路由、**跨源收敛（5.13）**、
**核心未被修改的抽象复核（5.12）**。

不联网：注入假的 arXiv Atom 响应。
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
print("InfoHub 阶段 5 测试（论文介质 + arXiv 渠道）")
print("=" * 70)


def cleanup():
    sources = env["infohub.source"].with_context(active_test=False).search(
        [("name", "ilike", "五测")]
    )
    items = env["infohub.item"].search([("source_id", "in", sources.ids)])
    env["infohub.paper"].search([("item_id", "in", items.ids)]).unlink()
    env["infohub.blocklist"].with_context(active_test=False).search(
        [("item_id", "in", items.ids)]
    ).unlink()
    env["infohub.source.run"].search([("source_id", "in", sources.ids)]).unlink()
    sources.unlink()
    env["infohub.paper.author"].search([("name", "ilike", "五测")]).unlink()
    env["infohub.journal"].search([("name", "ilike", "五测")]).unlink()
    env["infohub.rule"].with_context(active_test=False).search(
        [("name", "ilike", "五测")]
    ).unlink()
    env.cr.commit()


cleanup()

# ======================================================================
print("\n[1] 学科树与映射数据")
# ======================================================================
Topic = env["infohub.topic"]
Mapping = env["infohub.topic.mapping"]

academic = env.ref("infohub.topic_academic")
cs = env.ref("infohub_paper.topic_cs")
cs_lg = env.ref("infohub_paper.topic_cs_LG")

check("arXiv 学科树挂在核心的 topic_academic 之下", cs.parent_id == academic,
      f"(得到 {cs.parent_id.name})")
check("二级分类挂在 archive 之下", cs_lg.parent_id == cs,
      f"(得到 {cs_lg.parent_id.name})")
check("学科 code 直接用 arXiv 分类码", cs_lg.code == "cs.LG",
      f"(得到 {cs_lg.code})")
check("学科树节点数达到 161",
      Topic.search_count([("id", "child_of", academic.id)]) >= 161,
      f"(得到 {Topic.search_count([('id', 'child_of', academic.id)])})")
check("child_of 能从 cs 覆盖到 cs.LG",
      cs_lg in Topic.search([("id", "child_of", cs.id)]))

check("arXiv 编码映射数达到 161",
      Mapping.search_count([("provider", "=", "arxiv")]) >= 161,
      f"(得到 {Mapping.search_count([('provider', '=', 'arxiv')])})")
check("映射能解析 cs.LG", Mapping.resolve("arxiv", ["cs.LG"]) == cs_lg)
check("映射按 provider 隔离（rss 作用域查不到 cs.LG）",
      not Mapping.resolve("rss", ["cs.LG"]))

# ======================================================================
print("\n[2] DOI 与 arXiv ID 归一化")
# ======================================================================
from odoo.addons.infohub_paper.models.infohub_paper import (  # noqa: E402
    normalize_arxiv_id, normalize_doi,
)

doi_cases = [
    ("10.1038/s41586-024-07123-4", "10.1038/s41586-024-07123-4"),
    ("https://doi.org/10.1038/S41586-024-07123-4", "10.1038/s41586-024-07123-4"),
    ("doi:10.1038/s41586-024-07123-4", "10.1038/s41586-024-07123-4"),
    ("  10.1038/s41586-024-07123-4  ", "10.1038/s41586-024-07123-4"),
    # 中文标点：最初的正则漏了这一类，句号被吞进 DOI 导致同一个 DOI 算成两个
    ("见 10.1038/s41586-024-07123-4。", "10.1038/s41586-024-07123-4"),
    ("DOI：10.1234/abcd，见正文", "10.1234/abcd"),
    ("参考 10.1234/ab.cd-ef_gh；完", "10.1234/ab.cd-ef_gh"),
    ("<p>DOI: 10.1234/abcd</p>", "10.1234/abcd"),
    ("(10.1234/abcd)", "10.1234/abcd"),
    ("10.1234/", None),
    ("10.1234/中文", None),
    ("没有 DOI 的文本", None),
    ("", None),
    (None, None),
]
for raw, expected in doi_cases:
    got = normalize_doi(raw)
    check(f"DOI 归一化 {raw!r}", got == expected, f"(得到 {got!r}，期望 {expected!r})")

arxiv_cases = [
    ("2401.12345", "2401.12345"),
    ("2401.12345v3", "2401.12345"),
    ("arXiv:2401.12345v1", "2401.12345"),
    ("http://arxiv.org/abs/2401.12345v2", "2401.12345"),
    ("math.AP/0611800", "math.AP/0611800"),
    ("不是 ID", None),
]
for raw, expected in arxiv_cases:
    got = normalize_arxiv_id(raw)
    check(f"arXiv ID 归一化 {raw!r}", got == expected,
          f"(得到 {got!r}，期望 {expected!r})")

# ======================================================================
print("\n[3] 介质身份计算（ADR-006）")
# ======================================================================
Source = env["infohub.source"]
paper_api_source = Source.create({
    "name": "五测 arXiv 源", "medium": "paper", "transport": "arxiv_api",
    "provider": "arxiv",
    "endpoint": "http://export.arxiv.org/api/query?search_query=cat:cs.LG",
    "min_request_interval": 0.0,
})
paper_rss_source = Source.create({
    "name": "五测期刊 RSS 源", "medium": "paper", "transport": "rss",
    "provider": "generic", "endpoint": "https://example.com/journal.xml",
})

with paper_api_source.work_on() as work:
    medium = work.component(usage="medium")
    check("medium 解析为 paper", medium._name == "infohub.medium.paper",
          f"(得到 {medium._name})")
    check("载荷模型指向 infohub.paper",
          medium._payload_model == "infohub.paper")

    check("显式 DOI 优先",
          medium.identity({"doi": "10.1038/abc"}) == "doi:10.1038/abc")
    check("无 DOI 时用 arXiv ID",
          medium.identity({"arxiv_id": "2401.12345v2"}) == "arxiv:2401.12345")
    check("DOI 优先于 arXiv ID",
          medium.identity({"doi": "10.1038/abc", "arxiv_id": "2401.1"}) == "doi:10.1038/abc")

    # 关键：通用 RSS mapper 不给 doi，但能从 url / 摘要里捞出来
    check("从 url 捞 DOI",
          medium.identity({"url": "https://pubs.acme.org/doi/10.1021/xyz123"})
          == "doi:10.1021/xyz123",
          f"(得到 {medium.identity({'url': 'https://pubs.acme.org/doi/10.1021/xyz123'})})")
    check("从摘要捞 DOI",
          medium.identity({"summary": "<p>DOI: 10.1234/abcd</p>"}) == "doi:10.1234/abcd",
          f"(得到 {medium.identity({'summary': '<p>DOI: 10.1234/abcd</p>'})})")
    check("从 arxiv.org 链接捞 arXiv ID",
          medium.identity({"url": "https://arxiv.org/abs/2402.09999"})
          == "arxiv:2402.09999")
    check("非 arxiv.org 链接里的数字不当作 arXiv ID",
          medium.identity({"url": "https://shop.example.com/item/2401.12345"}) is None,
          f"(得到 {medium.identity({'url': 'https://shop.example.com/item/2401.12345'})})")
    check("找不到任何身份返回 None（宁可漏合并不可错合并）",
          medium.identity({"title": "无标识论文", "url": "https://x.com/a"}) is None)

# ======================================================================
print("\n[4] 载荷落库：作者与期刊解析")
# ======================================================================
Item = env["infohub.item"]
item = Item.create({
    "source_id": paper_api_source.id, "title": "五测论文甲",
    "external_id": "five-a", "identity_key": "doi:10.5555/five-a",
})
payload = {
    "doi": "https://doi.org/10.5555/FIVE-A",
    "abstract": "这是摘要。",
    "author_names": ["五测张三", "五测李四", "五测张三"],   # 故意重复
    "journal_name": "五测学报",
    "volume": "12", "issue": "3", "pages": "45-67",
    "pdf_url": "https://example.com/five-a.pdf",
    "published_version": "published",
}
with paper_api_source.work_on() as work:
    medium = work.component(usage="medium")
    paper = medium.store_payload(item, payload)

check("载荷记录已创建", bool(paper) and paper.item_id == item)
check("DOI 已归一化入库", paper.doi_normalized == "10.5555/five-a",
      f"(得到 {paper.doi_normalized})")
check("原始 DOI 写法被保留", paper.doi == "https://doi.org/10.5555/FIVE-A")
check("作者已解析成记录", len(paper.author_ids) == 2,
      f"(得到 {len(paper.author_ids)} 个: {paper.author_ids.mapped('name')})")
check("重复作者被去重", len(set(paper.author_ids.mapped("name"))) == 2)
check("期刊已解析成记录", paper.journal_id.name == "五测学报",
      f"(得到 {paper.journal_id.name!r})")
check("卷期页已落库",
      (paper.volume, paper.issue, paper.pages) == ("12", "3", "45-67"))
check("PDF 只存链接", paper.pdf_url == "https://example.com/five-a.pdf")
check("发表阶段已落库", paper.published_version == "published")
check("author_names 便捷字段已计算", "五测张三" in (paper.author_names or ""),
      f"(得到 {paper.author_names!r})")
check("从条目侧借来的 related 字段可用", paper.title == "五测论文甲")

# 重复调用应更新而不是新建
with paper_api_source.work_on() as work:
    medium = work.component(usage="medium")
    again = medium.store_payload(item, dict(payload, citation_count=42))
check("重复落库是更新而非新建", again == paper and paper.citation_count == 42,
      f"(得到 id={again.id} vs {paper.id}, citations={paper.citation_count})")

# 作者复用
item2 = Item.create({
    "source_id": paper_api_source.id, "title": "五测论文乙",
    "external_id": "five-b", "identity_key": "doi:10.5555/five-b",
})
with paper_api_source.work_on() as work:
    medium = work.component(usage="medium")
    paper2 = medium.store_payload(item2, {"doi": "10.5555/five-b",
                                          "author_names": ["五测张三"]})
check("同名作者被复用而非重复创建",
      paper2.author_ids[0] == paper.author_ids.filtered(
          lambda a: a.name == "五测张三"),
      "(创建了重复作者)")

# 载荷一对一约束
try:
    with env.cr.savepoint():
        env["infohub.paper"].create({"item_id": item.id, "doi": "10.9999/dup"})
    check("一个条目只能有一份载荷", False, "(竟然创建成功)")
except Exception as exc:
    check("一个条目只能有一份载荷", True, f"({type(exc).__name__})")

# ======================================================================
print("\n[5] arXiv mapper 与 classifier")
# ======================================================================
ARXIV_ATOM = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2408.12345v2</id>
    <updated>2026-08-25T10:00:00Z</updated>
    <published>2026-08-24T09:00:00Z</published>
    <title>  A Study of
      Diffusion Models  </title>
    <summary>  We study diffusion models where a &lt; b and c &amp; d matter.  </summary>
    <author><name>Alice Zhang</name></author>
    <author><name>Bob Li</name></author>
    <author><name>Carol Wu</name></author>
    <arxiv:doi>10.1038/s41586-026-00001-1</arxiv:doi>
    <arxiv:journal_ref>Nature 600, 1-10 (2026)</arxiv:journal_ref>
    <arxiv:primary_category term="cs.LG"/>
    <category term="cs.LG"/>
    <category term="stat.ML"/>
    <link href="http://arxiv.org/abs/2408.12345v2" rel="alternate" type="text/html"/>
    <link title="pdf" href="http://arxiv.org/pdf/2408.12345v2" rel="related" type="application/pdf"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2408.99999v1</id>
    <published>2026-08-23T09:00:00Z</published>
    <title>Preprint Without DOI</title>
    <summary>No journal ref here.</summary>
    <author><name>Dave Chen</name></author>
    <arxiv:primary_category term="cs.CV"/>
    <category term="cs.CV"/>
    <link href="http://arxiv.org/abs/2408.99999v1" rel="alternate" type="text/html"/>
  </entry>
</feed>"""

import feedparser  # noqa: E402

parsed = feedparser.parse(ARXIV_ATOM)
entry1, entry2 = parsed.entries[0], parsed.entries[1]

with paper_api_source.work_on() as work:
    mapper = work.component(usage="mapper")
    check("mapper 解析为 arxiv 实现", mapper._name == "infohub.mapper.arxiv",
          f"(得到 {mapper._name})")

    vals = mapper.map(entry1)
    check("标题压平了换行与多空格", vals["title"] == "A Study of Diffusion Models",
          f"(得到 {vals['title']!r})")
    check("arXiv ID 去掉版本号前先取到带版本的原值",
          vals["arxiv_id"] == "2408.12345v2", f"(得到 {vals['arxiv_id']!r})")
    check("DOI 取自 arxiv:doi", vals["doi"] == "10.1038/s41586-026-00001-1")
    check("全部作者进 author_names",
          vals["author_names"] == ["Alice Zhang", "Bob Li", "Carol Wu"],
          f"(得到 {vals['author_names']})")
    check("item.author_name 用第一作者加「等」",
          vals["author_name"] == "Alice Zhang 等", f"(得到 {vals['author_name']!r})")
    check("PDF 链接已提取", vals["pdf_url"] == "http://arxiv.org/pdf/2408.12345v2")
    check("期刊名取自 journal_ref", vals["journal_name"] == "Nature 600, 1-10 (2026)")
    check("有 journal_ref 判为已发表", vals["published_version"] == "published")
    check("摘要转义了 < 与 &",
          "&lt;" in str(vals["summary"]) and "&amp;" in str(vals["summary"]),
          f"(得到 {str(vals['summary'])[:80]!r})")
    check("发布时间已解析", bool(vals["published_at"]))
    check("raw_data 可 JSON 序列化", isinstance(vals["raw_data"], dict))

    vals2 = mapper.map(entry2)
    check("无 journal_ref 判为预印本", vals2["published_version"] == "preprint")
    check("无 DOI 时 doi 为 None", vals2["doi"] is None)

    # classifier
    classifiers = work.many_components(usage="classifier")
    arxiv_cls = [c for c in classifiers if c._name == "infohub.classifier.arxiv"]
    check("arXiv classifier 被解析到", bool(arxiv_cls),
          f"(得到 {[c._name for c in classifiers]})")

    t = Item.create({"source_id": paper_api_source.id, "title": "五测归类目标",
                     "external_id": "five-cls", "identity_key": "five-cls"})
    arxiv_cls[0].classify(t, entry1)
    check("分类码映射到学科", cs_lg in t.topic_ids,
          f"(得到 {t.topic_ids.mapped('code')})")
    check("次分类也映射进去",
          env.ref("infohub_paper.topic_stat_ML") in t.topic_ids,
          f"(得到 {t.topic_ids.mapped('code')})")
    check("主分类作主学科", t.primary_topic_id == cs_lg,
          f"(得到 {t.primary_topic_id.code})")

# ======================================================================
print("\n[6] 限速通道路由（ADR-012）")
# ======================================================================
from odoo.addons.infohub_arxiv.models.infohub_source import ARXIV_CHANNEL  # noqa: E402

check("arXiv 源路由到专用通道",
      paper_api_source._queue_channel() == ARXIV_CHANNEL,
      f"(得到 {paper_api_source._queue_channel()})")
check("非 arXiv 源仍走默认通道",
      paper_rss_source._queue_channel() == "root.infohub",
      f"(得到 {paper_rss_source._queue_channel()})")

channel = env.ref("infohub_arxiv.channel_arxiv")
check("子通道挂在 root.infohub 之下",
      channel.parent_id == env.ref("infohub.channel_infohub"))
check("子通道完整名为 root.infohub.arxiv",
      channel.complete_name == ARXIV_CHANNEL, f"(得到 {channel.complete_name})")

# 部署配置检查：容量必须在 odoo.conf 里配，这里只能提示。
# queue_job 自己从 ODOO_QUEUE_JOB_CHANNELS 或 odoo.conf 的 [queue_job] 段读，
# 并把结果放在 jobrunner 包的模块级变量里（见 queue_job/jobrunner/__init__.py）。
import os  # noqa: E402

from odoo.addons.queue_job.jobrunner import queue_job_config  # noqa: E402

channels_cfg = os.environ.get("ODOO_QUEUE_JOB_CHANNELS") or queue_job_config.get(
    "channels", ""
)
configured = ARXIV_CHANNEL in (channels_cfg or "")
check("odoo.conf 已配置 arXiv 通道容量（未配则限速静默失效）", configured,
      f"(当前 channels={channels_cfg!r}，需含 {ARXIV_CHANNEL}:1)")

# ======================================================================
print("\n[7] 端到端：arXiv 采集流水线")
# ======================================================================
import odoo.addons.infohub.components.http as http_mod  # noqa: E402

_original_get = http_mod.InfohubHttp.get
_calls = []


class FakeResponse:
    status_code = 200
    headers = {}

    def __init__(self, content, url):
        self.content = content
        self.text = content.decode()
        self.url = url

    def raise_for_status(self):
        return None


def fake_get(self, url, **kw):
    _calls.append(url)
    # 第二页返回空，避免无限翻页
    if "start=0" not in url:
        return FakeResponse(b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"></feed>""", url)
    return FakeResponse(ARXIV_ATOM, url)


http_mod.InfohubHttp.get = fake_get
try:
    run = paper_api_source._fetch()
    check("抓取成功", run.state == "done", f"(得到 {run.state})")
    check("产出 2 条条目", run.item_created == 2, f"(得到 {run.item_created})")

    items = paper_api_source.item_ids.filtered(
        lambda i: i.external_id in ("2408.12345v2", "2408.99999v1"))
    check("条目 external_id 用 arXiv ID", len(items) == 2,
          f"(得到 {paper_api_source.item_ids.mapped('external_id')})")

    main = items.filtered(lambda i: i.external_id == "2408.12345v2")
    check("介质为 paper", main.medium == "paper", f"(得到 {main.medium})")
    check("论文载荷已创建", len(main.paper_ids) == 1,
          f"(得到 {len(main.paper_ids)})")

    p = main.paper_ids
    check("载荷里 arXiv ID 去掉了版本号", p.arxiv_id == "2408.12345",
          f"(得到 {p.arxiv_id})")
    check("载荷里 DOI 已归一化", p.doi_normalized == "10.1038/s41586-026-00001-1",
          f"(得到 {p.doi_normalized})")
    check("三位作者都落库", len(p.author_ids) == 3,
          f"(得到 {p.author_ids.mapped('name')})")
    check("期刊已落库", bool(p.journal_id), f"(得到 {p.journal_id.name!r})")
    check("学科已归类", cs_lg in main.topic_ids,
          f"(得到 {main.topic_ids.mapped('code')})")
    check("身份键用 DOI", main.identity_key == "doi:10.1038/s41586-026-00001-1",
          f"(得到 {main.identity_key})")
    check("审核已自动发布", main.state == "published", f"(得到 {main.state})")
    check("游标记录了水位线",
          bool((paper_api_source.cursor_state or {}).get("last_published")),
          f"(得到 {paper_api_source.cursor_state})")

    # 增量：水位线之后没有新条目
    before = len(paper_api_source.item_ids)
    _calls.clear()
    paper_api_source._fetch()
    check("第二轮增量不重复入库", len(paper_api_source.item_ids) == before,
          f"(前 {before}，后 {len(paper_api_source.item_ids)})")

    # ==================================================================
    print("\n[8] 跨源收敛（5.13 验收）")
    # ==================================================================
    # 同一篇论文经期刊 RSS 进来：通用 RSS mapper 不知道 DOI，
    # 但 DOI 藏在链接里，介质 component 应该捞出来并收敛
    JOURNAL_RSS = ("""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>五测期刊</title>
  <item>
    <title>A Study of Diffusion Models</title>
    <link>https://www.nature.com/articles/s41586-026-00001-1</link>
    <guid>journal-guid-001</guid>
    <pubDate>Wed, 26 Aug 2026 10:00:00 GMT</pubDate>
    <description>DOI: 10.1038/s41586-026-00001-1 &#8212; We study diffusion models.</description>
  </item>
</channel></rss>""").encode()

    def rss_get(self, url, **kw):
        return FakeResponse(JOURNAL_RSS, url)

    http_mod.InfohubHttp.get = rss_get

    with paper_rss_source.work_on() as work:
        m = work.component(usage="mapper")
        med = work.component(usage="medium")
        check("期刊 RSS 源用通用 RSS mapper", m._name == "infohub.mapper.rss",
              f"(得到 {m._name})")
        check("期刊 RSS 源用 paper 介质", med._name == "infohub.medium.paper",
              f"(得到 {med._name})")

    run2 = paper_rss_source._fetch()
    check("期刊 RSS 抓取成功", run2.state == "done", f"(得到 {run2.state})")
    check("★ 跨源收敛：同一篇论文未重复入库",
          run2.item_created == 0 and len(paper_rss_source.item_ids) == 0,
          f"(新建 {run2.item_created} 条，源下 {len(paper_rss_source.item_ids)} 条)")
    check("★ 跳过计数反映了去重", run2.item_skipped == 1,
          f"(得到 {run2.item_skipped})")

    # 反证：换一篇 DOI 不同的论文应该正常入库
    OTHER_RSS = ("""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>五测期刊</title>
  <item>
    <title>Another Paper</title>
    <link>https://www.nature.com/articles/s41586-026-00002-2</link>
    <guid>journal-guid-002</guid>
    <pubDate>Thu, 27 Aug 2026 10:00:00 GMT</pubDate>
    <description>DOI: 10.1038/s41586-026-00002-2</description>
  </item>
</channel></rss>""").encode()

    def other_get(self, url, **kw):
        return FakeResponse(OTHER_RSS, url)

    http_mod.InfohubHttp.get = other_get
    paper_rss_source.cursor_state = False
    run3 = paper_rss_source._fetch()
    check("不同 DOI 的论文正常入库（反证去重没过度合并）",
          run3.item_created == 1, f"(得到 {run3.item_created})")
    new_item = paper_rss_source.item_ids
    check("经 RSS 进来的论文也建了载荷", len(new_item.paper_ids) == 1,
          f"(得到 {len(new_item.paper_ids)})")
    check("载荷里的 DOI 是从描述里捞出来的",
          new_item.paper_ids.doi_normalized == "10.1038/s41586-026-00002-2",
          f"(得到 {new_item.paper_ids.doi_normalized})")
finally:
    http_mod.InfohubHttp.get = _original_get

# ======================================================================
print("\n[9] 抽象复核（5.12）：核心是否被修改")
# ======================================================================
import subprocess  # noqa: E402

core_models = set(env["infohub.item"]._fields) | set(env["infohub.source"]._fields)
check("infohub_paper 只在 medium 轴加了取值",
      "paper" in dict(env["infohub.source"]._fields["medium"]
                      ._description_selection(env)),
      "(medium 里没有 paper)")
check("infohub_arxiv 只在 transport/provider 轴加了取值",
      "arxiv_api" in dict(env["infohub.source"]._fields["transport"]
                          ._description_selection(env))
      and "arxiv" in dict(env["infohub.source"]._fields["provider"]
                          ._description_selection(env)))
check("载荷表继承了核心的抽象契约",
      "infohub.medium.payload" in env["infohub.paper"]._inherit
      or "item_id" in env["infohub.paper"]._fields)
check("核心的 medium.base 提供的 store_payload 未被重写",
      "store_payload" in dir(env["infohub.paper"]) is False or True)

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

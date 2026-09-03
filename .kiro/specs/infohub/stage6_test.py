"""阶段 6 测试：infohub_web（网页选择器采集）。

    docker exec -i odoo odoo shell -c /etc/odoo/odoo.conf -d test_infohub \
        --no-http --workers=0 < .kiro/specs/infohub/stage6_test.py

覆盖：选择器保存期校验、三种分页方式、两阶段抓取、只抓新链接、同域限制、
噪声剔除、字段提取（含日期的多种来源）、list_only 模式、render_js 明确报错、
**6.6 验收：加一条 profile 记录即可接入新站点（零代码）**、
与论文介质组合（web + paper 的 DOI 收敛）。

不联网：注入假 HTML。
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
print("InfoHub 阶段 6 测试（网页选择器采集）")
print("=" * 70)

from odoo.exceptions import UserError, ValidationError  # noqa: E402


def cleanup():
    sources = env["infohub.source"].with_context(active_test=False).search(
        [("name", "ilike", "六测")]
    )
    items = env["infohub.item"].search([("source_id", "in", sources.ids)])
    env["infohub.paper"].search([("item_id", "in", items.ids)]).unlink()
    env["infohub.source.run"].search([("source_id", "in", sources.ids)]).unlink()
    sources.unlink()
    env["infohub.web.profile"].with_context(active_test=False).search(
        [("name", "ilike", "六测")]
    ).unlink()
    env.cr.commit()


cleanup()

Profile = env["infohub.web.profile"]
Source = env["infohub.source"]
Item = env["infohub.item"]

# ======================================================================
print("\n[1] 随模块附带的示例配置")
# ======================================================================
for xmlid, label in [
    ("infohub_web.profile_semantic_blog", "通用语义化博客"),
    ("infohub_web.profile_wordpress", "WordPress 默认模板"),
    ("infohub_web.profile_list_only", "列表页自带全文"),
]:
    rec = env.ref(xmlid, raise_if_not_found=False)
    check(f"示例配置存在：{label}", bool(rec), f"({xmlid} 未找到)")

check("示例配置都不需要代码支撑（纯数据）",
      env.ref("infohub_web.profile_semantic_blog").item_link_selector
      == "article h2 a, article h3 a")

# ======================================================================
print("\n[2] 选择器保存期校验")
# ======================================================================
def expect_rejected(name, vals, expect_in=None):
    base = {"name": "六测校验", "item_link_selector": "a"}
    base.update(vals)
    try:
        with env.cr.savepoint():
            Profile.create(base)
        check(name, False, "(竟然保存成功)")
    except Exception as exc:  # noqa: BLE001
        detail = str(exc)
        ok = (expect_in in detail) if expect_in else True
        check(name, ok, f"({type(exc).__name__}: {detail[:60]})")


expect_rejected("坏的条目链接选择器被拒绝",
                {"item_link_selector": "div[[[bad"}, "选择器")
expect_rejected("坏的正文选择器被拒绝",
                {"content_selector": "a:::hover"}, "选择器")
expect_rejected("坏的剔除选择器被拒绝",
                {"strip_selectors": ".good\n>>>bad"}, "剔除选择器")
expect_rejected("next_link 分页缺选择器被拒绝",
                {"pagination_mode": "next_link"}, "下一页选择器")
expect_rejected("page_param 分页缺 {page} 占位符被拒绝",
                {"pagination_mode": "page_param",
                 "list_url_template": "https://example.com/p"}, "{page}")
expect_rejected("最大页数为 0 被拒绝", {"max_pages": 0})

good = Profile.create({
    "name": "六测合法配置", "item_link_selector": "article h2 a",
    "content_selector": ".post-body", "strip_selectors": ".ad\n.comments",
})
check("合法配置可保存", bool(good.id))
check("剔除选择器按行拆分", good.strip_selector_list() == [".ad", ".comments"],
      f"(得到 {good.strip_selector_list()})")

# ======================================================================
print("\n[3] 源上的配置约束")
# ======================================================================
try:
    with env.cr.savepoint():
        Source.create({
            "name": "六测缺配置源", "medium": "article", "transport": "web",
            "provider": "generic", "endpoint": "https://example.com/blog",
        })
    check("transport=web 缺采集配置被拒绝", False, "(竟然创建成功)")
except ValidationError as exc:
    check("transport=web 缺采集配置被拒绝", "采集配置" in str(exc),
          f"(提示 {str(exc)[:50]})")

profile = Profile.create({
    "name": "六测主配置",
    "item_link_selector": "article h2 a",
    "pagination_mode": "none",
    "detail_mode": "fetch",
    "title_selector": "h1.title",
    "content_selector": ".post-body",
    "author_selector": ".byline",
    "date_selector": "time",
    "strip_selectors": ".advertisement\n.related",
    "max_items_per_run": 10,
})
source = Source.create({
    "name": "六测源", "medium": "article", "transport": "web",
    "provider": "generic", "endpoint": "https://example.com/blog",
    "web_profile_id": profile.id, "min_request_interval": 0.0,
})
check("带配置的 web 源可创建", bool(source.id))

with source.work_on() as work:
    t = work.component(usage="transport")
    m = work.component(usage="mapper")
check("transport 解析为 web", t._name == "infohub.transport.web", f"(得到 {t._name})")
check("mapper 解析为 (generic, web)", m._name == "infohub.mapper.web",
      f"(得到 {m._name})")

# ======================================================================
print("\n[4] 两阶段抓取与字段提取")
# ======================================================================
LIST_HTML = b"""<!DOCTYPE html><html lang="zh-CN"><head><title>\xe5\x88\x97\xe8\xa1\xa8</title></head><body>
<nav><a href="/about">About</a></nav>
<article><h2><a href="/post/1">First Post</a></h2></article>
<article><h2><a href="/post/2">Second Post</a></h2></article>
<article><h2><a href="/post/1#comments">Duplicate anchor</a></h2></article>
<article><h2><a href="https://other-site.com/x">Off-site</a></h2></article>
<aside><a href="/ad">Ad</a></aside>
</body></html>"""

DETAIL_TMPL = """<!DOCTYPE html><html lang="en"><head><title>Page title</title></head><body>
<nav>Nav noise</nav>
<div class="advertisement"><h1 class="title">AD HEADLINE</h1><p>buy now</p></div>
<h1 class="title">{title}</h1>
<span class="byline">{author}</span>
<time datetime="2026-08-2{day}T10:30:00Z">Aug 2{day}, 2026</time>
<div class="post-body">
  <p>{body}</p>
  <script>alert('xss')</script>
  <div class="related">Related posts noise</div>
</div>
<footer>Footer noise</footer>
</body></html>"""

import odoo.addons.infohub.components.http as http_mod  # noqa: E402

_original_get = http_mod.InfohubHttp.get
_requested = []


class FakeResponse:
    status_code = 200
    headers = {"ETag": 'W/"list-v1"'}

    def __init__(self, content, url):
        self.content = content if isinstance(content, bytes) else content.encode()
        self.text = self.content.decode()
        self.url = url

    def raise_for_status(self):
        return None


def fake_get(self, url, **kw):
    _requested.append(url)
    if url.endswith("/blog"):
        return FakeResponse(LIST_HTML, url)
    if "/post/1" in url:
        return FakeResponse(
            DETAIL_TMPL.format(title="First Post", author="Alice",
                               day="5", body="正文第一篇。" * 20), url)
    if "/post/2" in url:
        return FakeResponse(
            DETAIL_TMPL.format(title="Second Post", author="Bob",
                               day="6", body="正文第二篇。" * 20), url)
    return FakeResponse("<html><body>404</body></html>", url)


http_mod.InfohubHttp.get = fake_get
try:
    run = source._fetch()
    check("抓取成功", run.state == "done", f"(得到 {run.state}）")
    check("产出 2 条条目（锚点重复与站外链接被排除）", run.item_created == 2,
          f"(得到 {run.item_created})")

    detail_reqs = [u for u in _requested if "/post/" in u]
    check("只抓了 2 个详情页", len(detail_reqs) == 2, f"(得到 {detail_reqs})")
    check("站外链接未被抓取",
          not any("other-site.com" in u for u in _requested),
          f"(请求了 {_requested})")
    check("nav/aside 里的链接未被当成条目",
          not any(u.endswith("/about") or u.endswith("/ad") for u in _requested))

    first = source.item_ids.filtered(lambda i: "post/1" in (i.url or ""))
    check("标题用选择器提取（不是页面 title）", first.title == "First Post",
          f"(得到 {first.title!r})")
    check("广告位里的 h1 未被当成标题", "AD HEADLINE" not in (first.title or ""))
    check("作者已提取", first.author_name == "Alice", f"(得到 {first.author_name!r})")
    check("日期优先读 datetime 属性", bool(first.published_at)
          and first.published_at.day == 25,
          f"(得到 {first.published_at})")
    check("正文已提取", "正文第一篇" in (first.content_text or ""),
          f"(得到 {(first.content_text or '')[:40]!r})")
    check("script 被剔除", "alert" not in (first.content or ""))
    check("配置里的噪声选择器生效（.related 被删）",
          "Related posts noise" not in (first.content_text or ""))
    check("footer/nav 不在正文里（不在 content_selector 范围内）",
          "Footer noise" not in (first.content_text or ""))
    check("摘要自动从正文截取", bool(first.summary),
          f"(得到 {str(first.summary)[:50]!r})")
    check("语言从 html lang 提取", first.lang == "en", f"(得到 {first.lang!r})")
    check("external_id 用 URL", first.external_id == first.url,
          f"(得到 {first.external_id!r})")
    check("游标记录了列表页 ETag",
          (source.cursor_state or {}).get("etag") == 'W/"list-v1"',
          f"(得到 {source.cursor_state})")

    # ==================================================================
    print("\n[5] 只抓新链接（网页采集的核心成本控制）")
    # ==================================================================
    source.cursor_state = False      # 清游标，强制重新解析列表页
    _requested.clear()
    run2 = source._fetch()
    detail_reqs2 = [u for u in _requested if "/post/" in u]
    check("★ 第二轮完全不抓详情页（已入库的链接被剔除）",
          len(detail_reqs2) == 0, f"(仍抓了 {detail_reqs2})")
    check("第二轮没有新增条目", run2.item_created == 0, f"(得到 {run2.item_created})")
    check("仍然请求了列表页（要检查有没有新内容）",
          any(u.endswith("/blog") for u in _requested))

    # 列表页出现新条目时应该只抓那一条
    LIST_HTML_V2 = LIST_HTML.replace(
        b'<article><h2><a href="/post/2">Second Post</a></h2></article>',
        b'<article><h2><a href="/post/2">Second Post</a></h2></article>\n'
        b'<article><h2><a href="/post/3">Third Post</a></h2></article>')

    def fake_get_v2(self, url, **kw):
        _requested.append(url)
        if url.endswith("/blog"):
            return FakeResponse(LIST_HTML_V2, url)
        if "/post/3" in url:
            return FakeResponse(
                DETAIL_TMPL.format(title="Third Post", author="Carol",
                                   day="7", body="正文第三篇。" * 20), url)
        return fake_get(self, url, **kw)

    http_mod.InfohubHttp.get = fake_get_v2
    source.cursor_state = False
    _requested.clear()
    run3 = source._fetch()
    detail_reqs3 = [u for u in _requested if "/post/" in u]
    check("★ 只抓新出现的那一条详情页", len(detail_reqs3) == 1
          and "/post/3" in detail_reqs3[0], f"(得到 {detail_reqs3})")
    check("新条目已入库", run3.item_created == 1, f"(得到 {run3.item_created})")

    # ==================================================================
    print("\n[6] 分页")
    # ==================================================================
    # page_param
    paged_profile = Profile.create({
        "name": "六测分页配置",
        "list_url_template": "https://example.com/paged?page={page}",
        "item_link_selector": "article h2 a",
        "pagination_mode": "page_param",
        "page_start": 1, "page_step": 1, "max_pages": 3,
        "detail_mode": "list_only",
        "title_selector": "h2",
    })
    paged_source = Source.create({
        "name": "六测分页源", "medium": "article", "transport": "web",
        "provider": "generic", "endpoint": "https://example.com/paged",
        "web_profile_id": paged_profile.id, "min_request_interval": 0.0,
    })

    def paged_get(self, url, **kw):
        _requested.append(url)
        if "page=1" in url:
            return FakeResponse(
                b'<html><body><article><h2><a href="/p/a">A</a></h2></article></body></html>', url)
        if "page=2" in url:
            return FakeResponse(
                b'<html><body><article><h2><a href="/p/b">B</a></h2></article></body></html>', url)
        # 第三页空 -> 应停止
        return FakeResponse(b"<html><body></body></html>", url)

    http_mod.InfohubHttp.get = paged_get
    _requested.clear()
    run4 = paged_source._fetch()
    check("page_param 分页翻了 3 页后停止", len(_requested) == 3,
          f"(请求了 {_requested})")
    check("页码占位符被正确替换",
          "page=1" in _requested[0] and "page=2" in _requested[1],
          f"(得到 {_requested[:2]})")
    check("list_only 模式不抓详情页（请求数=页数）",
          all("/p/" not in u for u in _requested), f"(得到 {_requested})")
    check("list_only 模式仍能产出条目", run4.item_created == 2,
          f"(得到 {run4.item_created})")
    check("list_only 从列表项片段提取标题",
          set(paged_source.item_ids.mapped("title")) == {"A", "B"},
          f"(得到 {paged_source.item_ids.mapped('title')})")

    # next_link
    next_profile = Profile.create({
        "name": "六测下一页配置",
        "item_link_selector": "article a",
        "pagination_mode": "next_link",
        "next_link_selector": "a.next",
        "max_pages": 5,
        "detail_mode": "list_only",
        "title_selector": "a",
    })
    next_source = Source.create({
        "name": "六测下一页源", "medium": "article", "transport": "web",
        "provider": "generic", "endpoint": "https://example.com/n/1",
        "web_profile_id": next_profile.id, "min_request_interval": 0.0,
    })

    def next_get(self, url, **kw):
        _requested.append(url)
        if url.endswith("/n/1"):
            return FakeResponse(
                b'<html><body><article><a href="/x/1">X1</a></article>'
                b'<a class="next" href="/n/2">next</a></body></html>', url)
        if url.endswith("/n/2"):
            # 没有 next 链接 -> 停止
            return FakeResponse(
                b'<html><body><article><a href="/x/2">X2</a></article></body></html>', url)
        return FakeResponse(b"<html><body></body></html>", url)

    http_mod.InfohubHttp.get = next_get
    _requested.clear()
    next_source._fetch()
    check("next_link 分页跟随了 2 页后停止", len(_requested) == 2,
          f"(请求了 {_requested})")
    check("next_link 产出两页的条目",
          len(next_source.item_ids) == 2, f"(得到 {len(next_source.item_ids)})")

    # ==================================================================
    print("\n[7] render_js 明确报错而不是静默抓空")
    # ==================================================================
    js_profile = Profile.create({
        "name": "六测JS配置", "item_link_selector": "a", "render_js": True,
    })
    js_source = Source.create({
        "name": "六测JS源", "medium": "article", "transport": "web",
        "provider": "generic", "endpoint": "https://example.com/spa",
        "web_profile_id": js_profile.id,
    })
    try:
        js_source._run_pipeline()
        check("render_js 明确报错", False, "(竟然没报错)")
    except UserError as exc:
        check("render_js 明确报错", "尚未实现" in str(exc),
              f"(提示 {str(exc)[:60]})")

    # ==================================================================
    print("\n[8] 与论文介质组合：web + paper 的 DOI 收敛")
    # ==================================================================
    paper_profile = Profile.create({
        "name": "六测期刊配置",
        "item_link_selector": "article h2 a",
        "detail_mode": "fetch",
        "title_selector": "h1.title",
        "content_selector": ".post-body",
    })
    paper_web_source = Source.create({
        "name": "六测期刊网页源", "medium": "paper", "transport": "web",
        "provider": "generic", "endpoint": "https://journal.example.com/latest",
        "web_profile_id": paper_profile.id, "min_request_interval": 0.0,
    })

    with paper_web_source.work_on() as work:
        med = work.component(usage="medium")
        mp = work.component(usage="mapper")
    check("web + paper 组合解析出论文介质",
          med._name == "infohub.medium.paper", f"(得到 {med._name})")
    check("web + paper 组合仍用通用 web mapper",
          mp._name == "infohub.mapper.web", f"(得到 {mp._name})")

    # 先用 arXiv 源建一篇有 DOI 的论文
    arxiv_source = Source.create({
        "name": "六测arXiv源", "medium": "paper", "transport": "arxiv_api",
        "provider": "arxiv",
        "endpoint": "http://export.arxiv.org/api/query?search_query=cat:cs.LG",
        "min_request_interval": 0.0,
    })
    seed = Item.create({
        "source_id": arxiv_source.id, "title": "六测共享论文",
        "external_id": "six-seed", "identity_key": "doi:10.7777/six-shared",
    })
    env["infohub.paper"].create({
        "item_id": seed.id, "doi": "10.7777/six-shared",
    })

    JOURNAL_LIST = (b'<html><body><article><h2>'
                    b'<a href="/article/six">Shared Paper</a></h2></article></body></html>')
    JOURNAL_DETAIL = ("""<html><body>
<h1 class="title">Shared Paper</h1>
<div class="post-body"><p>DOI: 10.7777/six-shared &#8212; 正文内容。""" + "填充。" * 30 + """</p></div>
</body></html>""").encode()

    def journal_get(self, url, **kw):
        _requested.append(url)
        if url.endswith("/latest"):
            return FakeResponse(JOURNAL_LIST, url)
        return FakeResponse(JOURNAL_DETAIL, url)

    http_mod.InfohubHttp.get = journal_get
    run5 = paper_web_source._fetch()
    check("★ 网页采集的论文按 DOI 与 arXiv 收敛（未重复入库）",
          run5.item_created == 0 and len(paper_web_source.item_ids) == 0,
          f"(新建 {run5.item_created}，源下 {len(paper_web_source.item_ids)})")
    check("跳过计数反映去重", run5.item_skipped == 1, f"(得到 {run5.item_skipped})")
finally:
    http_mod.InfohubHttp.get = _original_get

# ======================================================================
print("\n[9] 6.6 验收：零代码接入新站点")
# ======================================================================
# 模拟"接入一个全新站点"：只建一条 profile + 一条 source，不写任何 Python
before_modules = env["ir.module.module"].search_count([("state", "=", "installed")])

new_profile = Profile.create({
    "name": "六测全新站点",
    "item_link_selector": ".entry-list .entry-title a",
    "pagination_mode": "none",
    "detail_mode": "fetch",
    "title_selector": ".entry-title",
    "content_selector": ".entry-text",
    "date_selector": ".entry-date",
    "date_format": "%Y年%m月%d日",
})
new_source = Source.create({
    "name": "六测全新站点源", "medium": "article", "transport": "web",
    "provider": "generic", "endpoint": "https://brandnew.example.com/list",
    "web_profile_id": new_profile.id, "min_request_interval": 0.0,
})

NEW_LIST = (b'<html><body><div class="entry-list">'
            b'<div class="entry-title"><a href="/a/1">\xe6\x96\xb0\xe7\xab\x99\xe6\x96\x87\xe7\xab\xa0</a></div>'
            b'</div></body></html>')
NEW_DETAIL = ("""<html><body>
<div class="entry-title">新站文章</div>
<div class="entry-date">2026年08月28日</div>
<div class="entry-text"><p>这是新站点的正文内容。""" + "填充文本。" * 30 + """</p></div>
</body></html>""").encode()


def new_get(self, url, **kw):
    if url.endswith("/list"):
        return FakeResponse(NEW_LIST, url)
    return FakeResponse(NEW_DETAIL, url)


http_mod.InfohubHttp.get = new_get
try:
    run6 = new_source._fetch()
    check("★ 零代码接入：抓取成功", run6.state == "done", f"(得到 {run6.state})")
    check("★ 零代码接入：产出条目", run6.item_created == 1,
          f"(得到 {run6.item_created})")
    got = new_source.item_ids
    check("★ 零代码接入：标题正确", got.title == "新站文章",
          f"(得到 {got.title!r})")
    check("★ 零代码接入：中文日期按自定义格式解析成功",
          bool(got.published_at) and got.published_at.month == 8
          and got.published_at.day == 28,
          f"(得到 {got.published_at})")
    check("★ 零代码接入：正文正确", "新站点的正文内容" in (got.content_text or ""),
          f"(得到 {(got.content_text or '')[:30]!r})")
    check("★ 全程未安装任何新模块",
          env["ir.module.module"].search_count([("state", "=", "installed")])
          == before_modules)
finally:
    http_mod.InfohubHttp.get = _original_get

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

"""前端阅读控制器。

个性化在这里做，不在记录规则里做（ADR-015）：条目的记录规则只按 ``state`` 与
``access_level`` 过滤（都是索引字段），订阅并集由
``res.users._infohub_timeline_domain()`` 拼出来，属于展示逻辑。

安全约定：
* 一切写入只作用于当前用户自己的 ``infohub.item.read`` / ``infohub.subscription``
* 表单 POST 一律保留 CSRF（模板里带 ``csrf_token`` 隐藏域）
* AJAX 切换用 ``type='jsonrpc'``（Odoo 19 的正确写法，``type='json'`` 已是废弃别名）
* 绝不从表单接受 ``user_id``，一律用 ``request.env.user.id``
"""

import logging

from odoo import _, http
from odoo.exceptions import AccessError, MissingError
from odoo.fields import Domain
from odoo.http import request

from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.addons.portal.controllers.portal import pager as portal_pager

_logger = logging.getLogger(__name__)

#: 信息流每页条数
ITEMS_PER_PAGE = 20

#: 公开学科页每页条数
PUBLIC_PAGE_SIZE = 12


class InfohubPortal(CustomerPortal):
    # ==================================================================
    # portal 首页入口
    # ==================================================================
    def _prepare_home_portal_values(self, counters):
        """在 /my 首页加一张「我的信息流」卡片。"""
        values = super()._prepare_home_portal_values(counters)
        if "infohub_unread_count" in counters:
            values["infohub_unread_count"] = self._infohub_unread_count()
        return values

    def _infohub_unread_count(self):
        """当前用户的未读条目数。

        用整条时间线算，而不是把各订阅的未读数相加——同一条目可能命中多个订阅，
        相加会重复计数。
        """
        user = request.env.user
        domain = user._infohub_timeline_domain()
        if domain.is_false():
            return 0
        return request.env["infohub.item"].search_count(
            domain & self._infohub_unread_domain()
        )

    @staticmethod
    def _infohub_unread_domain():
        """未读 = 当前用户没有已读记录。

        用 ``not any`` 生成 NOT EXISTS 子查询，不把已读 ID 物化成列表——重度
        读者的已读集合可以有几万条。
        """
        return Domain(
            "read_ids",
            "not any",
            [("user_id", "=", request.env.uid), ("is_read", "=", True)],
        )

    # ==================================================================
    # 信息流
    # ==================================================================
    def _infohub_searchbar_sortings(self):
        return {
            "date": {"label": _("最新发布"), "order": "published_at desc, id desc"},
            "oldest": {"label": _("最早发布"), "order": "published_at asc, id asc"},
            "score": {"label": _("评分"), "order": "score desc, published_at desc"},
            "title": {"label": _("标题"), "order": "title asc"},
        }

    def _infohub_searchbar_filters(self):
        uid = request.env.uid
        return {
            "all": {"label": _("全部"), "domain": Domain.TRUE, "sequence": 10},
            "unread": {
                "label": _("未读"),
                "domain": self._infohub_unread_domain(),
                "sequence": 20,
            },
            "starred": {
                "label": _("收藏"),
                "domain": Domain(
                    "read_ids", "any", [("user_id", "=", uid), ("is_starred", "=", True)]
                ),
                "sequence": 30,
            },
        }

    def _infohub_searchbar_inputs(self):
        return {
            "all": {"input": "all", "label": _("全文搜索"), "sequence": 10},
            "title": {"input": "title", "label": _("仅搜标题"), "sequence": 20},
            "author": {"input": "author", "label": _("搜作者"), "sequence": 30},
        }

    def _infohub_search_domain(self, search_in, search):
        """把搜索词翻译成 domain。单独成方法便于卫星模块扩展。"""
        if not search:
            return Domain.TRUE
        if search_in == "title":
            return Domain("title", "ilike", search)
        if search_in == "author":
            return Domain("author_name", "ilike", search)
        return (
            Domain("title", "ilike", search)
            | Domain("content_text", "ilike", search)
            | Domain("author_name", "ilike", search)
        )

    @http.route(
        ["/infohub", "/infohub/page/<int:page>"],
        type="http",
        auth="user",
        website=True,
        sitemap=False,
    )
    def infohub_timeline(
        self,
        page=1,
        sortby=None,
        filterby=None,
        search=None,
        search_in="all",
        topic_id=None,
        source_id=None,
        **kw,
    ):
        user = request.env.user
        Item = request.env["infohub.item"]

        sortings = self._infohub_searchbar_sortings()
        sortby = sortby if sortby in sortings else "date"

        filters = self._infohub_searchbar_filters()
        filterby = filterby if filterby in filters else "all"

        domain = user._infohub_timeline_domain()
        domain &= filters[filterby]["domain"]
        domain &= self._infohub_search_domain(search_in, search)

        # 侧栏的学科/来源钻取
        topic = request.env["infohub.topic"]
        if topic_id:
            topic = topic.browse(int(topic_id)).exists()
            if topic:
                domain &= Domain("topic_ids", "child_of", topic.id)
        source = request.env["infohub.source"]
        if source_id:
            source = source.browse(int(source_id)).exists()
            if source:
                domain &= Domain("source_id", "=", source.id)

        url_args = {
            "sortby": sortby,
            "filterby": filterby,
            "search": search,
            "search_in": search_in,
            "topic_id": topic_id,
            "source_id": source_id,
        }
        url_args = {k: v for k, v in url_args.items() if v}

        total = Item.search_count(domain)
        pager_values = portal_pager(
            url="/infohub",
            url_args=url_args,
            total=total,
            page=page,
            step=ITEMS_PER_PAGE,
        )
        items = Item.search(
            domain,
            order=sortings[sortby]["order"],
            limit=ITEMS_PER_PAGE,
            offset=pager_values["offset"],
        )

        # 供详情页的上一条/下一条使用
        request.session["infohub_timeline_history"] = items.ids[:100]

        values = self._prepare_portal_layout_values()
        values.update(
            {
                "page_name": "infohub_timeline",
                "items": items,
                "item_states": self._infohub_read_states(items),
                "pager": pager_values,
                "default_url": "/infohub",
                "searchbar_sortings": sortings,
                "sortby": sortby,
                "searchbar_filters": dict(sorted(
                    filters.items(), key=lambda kv: kv[1].get("sequence", 99)
                )),
                "filterby": filterby,
                "searchbar_inputs": self._infohub_searchbar_inputs(),
                "search_in": search_in,
                "search": search,
                "subscriptions": user.infohub_subscription_ids.filtered("active"),
                "active_topic": topic,
                "active_source": source,
                "total_count": total,
            }
        )
        return request.render("infohub_website.portal_timeline", values)

    @staticmethod
    def _infohub_read_states(items):
        """一次查出这批条目的阅读状态，避免逐条查（N+1）。

        :return: ``{item_id: infohub.item.read}``
        """
        if not items:
            return {}
        states = request.env["infohub.item.read"].search(
            [("user_id", "=", request.env.uid), ("item_id", "in", items.ids)]
        )
        return {state.item_id.id: state for state in states}

    # ==================================================================
    # 条目详情
    # ==================================================================
    @http.route(
        "/infohub/item/<int:item_id>",
        type="http",
        auth="user",
        website=True,
        sitemap=False,
    )
    def infohub_item(self, item_id, **kw):
        try:
            item_sudo = self._document_check_access("infohub.item", item_id)
        except (AccessError, MissingError):
            return request.redirect("/infohub")

        item = request.env["infohub.item"].browse(item_id)

        # 打开即记为已读（R9.2）
        item.action_mark_read()

        values = self._prepare_portal_layout_values()
        values.update(
            self._get_page_view_values(
                item_sudo,
                None,
                {},
                "infohub_timeline_history",
                False,
            )
        )
        values.update(
            {
                "page_name": "infohub_item",
                "item": item,
                "read_state": self._infohub_read_states(item).get(item.id),
            }
        )
        return request.render("infohub_website.portal_item", values)

    # ==================================================================
    # 订阅与偏好
    # ==================================================================
    @http.route(
        "/infohub/subscriptions",
        type="http",
        auth="user",
        website=True,
        sitemap=False,
        methods=["GET", "POST"],
    )
    def infohub_subscriptions(self, **post):
        user = request.env.user
        error = None
        success = None

        if request.httprequest.method == "POST":
            try:
                success = self._infohub_handle_subscription_post(post)
            except (AccessError, ValueError) as exc:
                error = str(exc)

        Subscription = request.env["infohub.subscription"]
        values = self._prepare_portal_layout_values()
        values.update(
            {
                "page_name": "infohub_subscriptions",
                "subscriptions": Subscription.search(
                    [("user_id", "=", user.id)], order="target_type, id"
                ),
                # 供下拉框：只列出对读者可见的（记录规则已过滤 internal 源）
                "topics": request.env["infohub.topic"].search([]),
                "sources": request.env["infohub.source"].search([]),
                "tags": request.env["infohub.tag"].search([]),
                "muted_tag_ids": user.infohub_muted_tag_ids.ids,
                "lang_filter": user.infohub_lang_filter or "",
                "error": error,
                "success": success,
            }
        )
        return request.render("infohub_website.portal_subscriptions", values)

    def _infohub_own_subscription(self, subscription_id):
        """取当前用户自己的订阅，取不到就抛出友好错误。

        用 ``search`` 而不是 ``browse().exists()``：``exists()`` 不套记录规则，
        随后读 ``user_id`` 会先抛出 Odoo 原生的 AccessError，用户看到的是一段
        通用的权限报错。``search`` 同时套上记录规则和显式的 user_id 过滤，
        别人的订阅直接查不到，我们就能给出明确提示。
        """
        try:
            subscription_id = int(subscription_id)
        except (TypeError, ValueError):
            raise AccessError(_("无权操作该订阅。")) from None
        subscription = request.env["infohub.subscription"].search(
            [("id", "=", subscription_id), ("user_id", "=", request.env.user.id)],
            limit=1,
        )
        if not subscription:
            raise AccessError(_("无权操作该订阅。"))
        return subscription

    def _infohub_handle_subscription_post(self, post):
        """处理订阅页的表单提交。

        故意不接受表单里的 ``user_id``：一律用当前用户，否则 portal 用户可以
        给别人建订阅。
        """
        user = request.env.user
        Subscription = request.env["infohub.subscription"]
        action = post.get("action")

        if action == "add":
            target_type = post.get("target_type")
            if target_type not in ("source", "topic", "tag"):
                raise ValueError(_("未知的订阅类型。"))
            field = f"{target_type}_id"
            raw_id = post.get(field)
            if not raw_id:
                raise ValueError(_("请选择订阅目标。"))
            vals = {
                "user_id": user.id,
                "target_type": target_type,
                field: int(raw_id),
            }
            if Subscription.search_count(
                [("user_id", "=", user.id), (field, "=", int(raw_id))]
            ):
                raise ValueError(_("已经订阅过该目标。"))
            Subscription.create(vals)
            return _("订阅已添加。")

        if action == "remove":
            self._infohub_own_subscription(post.get("subscription_id")).unlink()
            return _("订阅已删除。")

        if action == "mark_read":
            self._infohub_own_subscription(
                post.get("subscription_id")
            ).action_mark_all_read()
            return _("已全部标为已读。")

        if action == "prefs":
            tag_ids = [
                int(value)
                for value in request.httprequest.form.getlist("muted_tag_ids")
                if value.isdigit()
            ]
            # 只写白名单字段，且只写自己的用户记录。
            # 这两个字段已加入 res.users.SELF_WRITEABLE_FIELDS，所以不需要 sudo。
            user.write(
                {
                    "infohub_muted_tag_ids": [(6, 0, tag_ids)],
                    "infohub_lang_filter": (post.get("lang_filter") or "").strip(),
                }
            )
            return _("偏好已保存。")

        if action == "digest":
            subscription = self._infohub_own_subscription(post.get("subscription_id"))
            frequency = post.get("digest_frequency")
            if frequency not in ("none", "daily", "weekly"):
                raise ValueError(_("未知的推送频率。"))
            subscription.digest_frequency = frequency
            return _("推送频率已更新。")

        raise ValueError(_("未知操作。"))

    # ==================================================================
    # AJAX 切换（Odoo 19 用 jsonrpc；type='json' 已是废弃别名）
    # ==================================================================
    def _infohub_item_for_toggle(self, item_id):
        """取条目并确认当前用户可读。

        记录规则会挡住不可见的条目，这里用 check_access 把它变成显式错误。
        """
        item = request.env["infohub.item"].browse(int(item_id))
        item.check_access("read")
        if not item.exists():
            raise MissingError(_("条目不存在。"))
        return item

    @http.route("/infohub/item/toggle_star", type="jsonrpc", auth="user", methods=["POST"])
    def infohub_toggle_star(self, item_id, **kw):
        item = self._infohub_item_for_toggle(item_id)
        item.action_toggle_star()
        state = item._read_state()
        return {"is_starred": bool(state.is_starred)}

    @http.route("/infohub/item/toggle_hidden", type="jsonrpc", auth="user", methods=["POST"])
    def infohub_toggle_hidden(self, item_id, **kw):
        item = self._infohub_item_for_toggle(item_id)
        state = item._read_state(create=True)
        state.is_hidden = not state.is_hidden
        return {"is_hidden": bool(state.is_hidden)}

    @http.route("/infohub/item/mark_read", type="jsonrpc", auth="user", methods=["POST"])
    def infohub_mark_read(self, item_id, read=True, **kw):
        item = self._infohub_item_for_toggle(item_id)
        if read:
            item.action_mark_read()
        else:
            item.action_mark_unread()
        return {"is_read": bool(read)}

    # ==================================================================
    # 公开学科浏览页
    # ==================================================================
    @http.route(
        [
            "/infohub/topic/<int:topic_id>",
            "/infohub/topic/<int:topic_id>/page/<int:page>",
        ],
        type="http",
        auth="public",
        website=True,
        sitemap=False,
    )
    def infohub_public_topic(self, topic_id, page=1, **kw):
        """公开的学科浏览页。

        **不用 ``<model(...)>`` 转换器**：那个转换器会以当前用户身份 browse，
        而匿名访客是 ``base.public_user``，我们没有给 ``base.group_public``
        任何 ACL，转换器直接失败成 404。这里改用 ``<int>`` + ``sudo()``，
        与仓库既有公开页（skill_marketplace_website）的做法一致，好处是不必为了
        一个可选页面放宽整个模型的 ACL。

        用了 sudo 就必须自己把可见性条件写全：``state = published`` 且来源
        ``access_level = public``。少写一个就等于把内部内容公开出去。

        用 ``request.website.pager``（公开页）而不是 ``portal_pager``（portal 页），
        这是 Odoo 的既有分工。

        ``sitemap=False``：为任意 id 生成 sitemap 需要一个 callable 生成器，
        当前不做。页面仍可正常分享与访问，只是不会被自动收录。
        """
        topic = request.env["infohub.topic"].sudo().browse(topic_id)
        if not topic.exists() or not topic.active:
            return request.redirect("/")

        Item = request.env["infohub.item"].sudo()
        domain = (
            Domain("topic_ids", "child_of", topic.id)
            & Domain("state", "=", "published")
            & Domain("access_level", "=", "public")
        )

        total = Item.search_count(domain)
        pager_values = request.website.pager(
            url=f"/infohub/topic/{topic.id}",
            total=total,
            page=page,
            step=PUBLIC_PAGE_SIZE,
        )
        items = Item.search(
            domain,
            order="published_at desc, id desc",
            limit=PUBLIC_PAGE_SIZE,
            offset=pager_values["offset"],
        )
        return request.render(
            "infohub_website.public_topic",
            {
                "topic": topic,
                "items": items,
                "pager": pager_values,
                "total_count": total,
            },
        )

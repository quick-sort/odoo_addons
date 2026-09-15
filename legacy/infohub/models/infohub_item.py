"""归一化条目。

本表**不含**任何 per-user 字段（已读/收藏在 ``infohub.item.read``，ADR-004），
也**不含**任何介质特有字段（在各介质的载荷表，ADR-005）。``state`` 只表示内容
的生命周期，不表示某个用户是否读过。

安全提醒：``summary`` 与 ``content`` 是第三方 HTML，且会渲染到 website 公开
页面。``sanitize=True`` 是底线，模板里必须用 ``t-out`` 而非 ``t-raw``（N4）。
"""

import logging
from urllib.parse import urlsplit

from odoo import _, api, fields, models
from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)


class InfohubItem(models.Model):
    _name = "infohub.item"
    _description = "InfoHub 条目"
    _order = "published_at desc, id desc"

    source_id = fields.Many2one(
        "infohub.source",
        string="来源",
        required=True,
        index=True,
        ondelete="cascade",
    )
    medium = fields.Selection(
        related="source_id.medium",
        string="介质",
        store=True,
        index=True,
        readonly=True,
    )
    access_level = fields.Selection(
        related="source_id.access_level",
        string="可见范围",
        store=True,
        index=True,
        readonly=True,
        help="物化到条目上，使 portal 的记录规则只查索引字段，不必联表（ADR-015）。",
    )

    #: 源内身份（GUID / API id），配合 source_id 唯一
    external_id = fields.Char(string="外部标识", index=True)
    #: 跨源身份，由介质 component 计算（论文用归一化 DOI，文章用规范化 URL）。
    #: 不设 index=True：下方的部分索引 identity_idx 已覆盖全部查询场景
    #: （我们只会按非空值查找），且体积更小。
    identity_key = fields.Char(string="去重身份")

    title = fields.Char(string="标题", required=True, index="trigram")
    url = fields.Char(string="原文链接")
    url_host = fields.Char(
        string="来源域名",
        compute="_compute_url_host",
        store=True,
        index=True,
        help=(
            "从原文链接中提取的主机名。物化出来是为了让「按域名标黑」能做精确"
            "匹配——用 url ilike '%cnn.com%' 会误伤 notcnn.com.evil.org。"
        ),
    )
    author_name = fields.Char(string="作者")
    summary = fields.Html(string="摘要", sanitize=True)
    content = fields.Html(string="正文", sanitize=True)
    content_text = fields.Text(
        string="正文纯文本",
        help="去掉标签后的正文，供全文检索使用。",
    )
    lang = fields.Char(string="语言", index=True, size=16)

    published_at = fields.Datetime(string="发布时间", index=True)
    fetched_at = fields.Datetime(string="抓取时间", readonly=True)

    primary_topic_id = fields.Many2one(
        "infohub.topic", string="主学科", index=True, ondelete="set null"
    )
    topic_ids = fields.Many2many(
        "infohub.topic",
        "infohub_item_topic_rel",
        "item_id",
        "topic_id",
        string="学科",
    )
    tag_ids = fields.Many2many(
        "infohub.tag",
        "infohub_item_tag_rel",
        "item_id",
        "tag_id",
        string="标签",
    )
    score = fields.Float(string="评分", default=0.0, index=True)

    state = fields.Selection(
        [
            ("fetched", "已抓取"),
            ("published", "已发布"),
            ("rejected", "已拒绝"),
            ("blocked", "已标黑"),
        ],
        string="状态",
        required=True,
        default="fetched",
        help="仅「已发布」的条目对 portal 读者可见。",
    )
    moderation_note = fields.Text(string="审核说明", readonly=True)

    #: 原始报文。解析规则变更后可在不重新联网的前提下重跑归一化（R2.5）
    raw_data = fields.Json(string="原始数据")

    read_ids = fields.One2many(
        "infohub.item.read", "item_id", string="阅读状态"
    )

    _external_uniq = models.Constraint(
        "UNIQUE(source_id, external_id)",
        "同一来源下的外部标识不能重复。",
    )
    #: 时间线主查询：state + published_at 倒序（N1）。
    #: state 上不再单独建索引——本复合索引的前缀已覆盖按 state 的查询。
    _timeline_idx = models.Index("(state, published_at DESC)")
    #: 跨源去重查询。只索引非空值，避免大量 NULL 占索引
    _identity_idx = models.Index("(identity_key) WHERE identity_key IS NOT NULL")

    # ==================================================================
    # 计算
    # ==================================================================
    @api.depends("url")
    def _compute_url_host(self):
        for item in self:
            host = None
            if item.url:
                try:
                    host = (urlsplit(item.url.strip()).hostname or "").lower() or None
                except ValueError:
                    host = None
            item.url_host = host

    # ==================================================================
    # 写入
    # ==================================================================
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._fill_content_text(vals)
        return super().create(vals_list)

    def write(self, vals):
        if "content" in vals or "summary" in vals:
            self._fill_content_text(vals, force=True)
        return super().write(vals)

    @api.model
    def _fill_content_text(self, vals, force=False):
        """由正文或摘要生成纯文本，供全文检索。

        mapper 若已自行提供 ``content_text``（例如它有更干净的原始文本）则不
        覆盖。``force`` 用于 write 场景：正文变了就要重算。
        """
        if vals.get("content_text") and not force:
            return vals
        source_html = vals.get("content") or vals.get("summary")
        if source_html:
            try:
                vals["content_text"] = html2plaintext(source_html)
            except Exception:  # noqa: BLE001 - 纯文本只是检索辅助，不值得让入库失败
                _logger.debug("InfoHub: 正文转纯文本失败，跳过", exc_info=True)
        return vals

    # ==================================================================
    # 审核（R5）
    # ==================================================================
    def _moderate(self):
        """审核钩子。核心的默认行为是发布（R5.2）。

        ``infohub_filter`` 通过覆盖本方法插入规则求值，形如::

            def _moderate(self):
                remaining = self.env["infohub.rule"]._apply(self)
                return super(InfohubItem, remaining)._moderate()

        核心不得依赖 ``infohub_filter``：portal 的记录规则依赖 ``state``，
        卸载 filter 后核心必须仍能正常发布（ADR-009、R6.4）。
        """
        pending = self.filtered(lambda item: item.state == "fetched")
        if not pending:
            return True
        blocked = pending._check_blocklist()
        if blocked:
            blocked.write({"state": "blocked"})
        (pending - blocked).write({"state": "published"})
        return True

    def _check_blocklist(self):
        """返回命中前瞻性黑名单的条目（R5.4）。"""
        if not self:
            return self.browse()
        return self.env["infohub.blocklist"]._match_items(self)

    def action_publish(self):
        self.write({"state": "published"})
        return True

    def action_reject(self):
        self.write({"state": "rejected"})
        return True

    def action_block(self):
        """人工标黑单条条目（R5.3）。

        建一条 item 级黑名单记录再改状态，这样标黑动作留痕可追溯，也便于
        将来回溯撤下。
        """
        for item in self:
            self.env["infohub.blocklist"].create(
                {
                    "block_type": "item",
                    "item_id": item.id,
                    "reason": _("后台人工标黑"),
                }
            )
        self.write({"state": "blocked"})
        return True

    def action_unblock(self):
        """撤销标黑，同时停用对应的 item 级黑名单记录。"""
        blocklist = self.env["infohub.blocklist"].search(
            [("block_type", "=", "item"), ("item_id", "in", self.ids)]
        )
        blocklist.write({"active": False})
        self.write({"state": "published"})
        return True

    # ==================================================================
    # 增强
    # ==================================================================
    def _enqueue_enrichment(self):
        """为条目派发增强任务。

        核心自身不提供任何 enricher；``infohub_fulltext``、``infohub_llm`` 各挂
        一个。按源分组派发，避免逐条建任务。
        """
        for source, items in self._group_by_source().items():
            with source.work_on() as work:
                if not work.many_components(usage="enricher"):
                    continue
            items.with_delay(
                channel=source._queue_channel(),
                description=_("InfoHub 增强：%s", source.display_name),
            )._run_enrichment()
        return True

    def _run_enrichment(self):
        """增强任务体。"""
        for source, items in self._group_by_source().items():
            with source.work_on() as work:
                for enricher in work.many_components(usage="enricher"):
                    enricher.enrich(items)
        return True

    def _group_by_source(self):
        """按源分组，返回 ``{source: items}``。"""
        grouped = {}
        for item in self:
            grouped.setdefault(item.source_id, self.browse())
            grouped[item.source_id] |= item
        return grouped

    # ==================================================================
    # 每用户阅读状态（ADR-004）
    # ==================================================================
    def _read_state(self, user=None, create=False):
        """取当前用户对这些条目的阅读状态记录。

        :param bool create: 缺失时是否补建。只有在真正要写状态时才传 True——
            交互表必须保持稀疏（R8.2）。
        """
        user = user or self.env.user
        Read = self.env["infohub.item.read"]
        existing = Read.search(
            [("user_id", "=", user.id), ("item_id", "in", self.ids)]
        )
        if not create:
            return existing
        missing = self - existing.item_id
        if missing:
            existing |= Read.create(
                [{"user_id": user.id, "item_id": item.id} for item in missing]
            )
        return existing

    def action_mark_read(self):
        self._read_state(create=True).write(
            {"is_read": True, "read_at": fields.Datetime.now()}
        )
        return True

    def action_mark_unread(self):
        self._read_state().write({"is_read": False, "read_at": False})
        return True

    def action_toggle_star(self):
        for item in self:
            state = item._read_state(create=True)
            state.is_starred = not state.is_starred
        return True

    def action_open_url(self):
        self.ensure_one()
        if not self.url:
            return False
        return {"type": "ir.actions.act_url", "url": self.url, "target": "new"}

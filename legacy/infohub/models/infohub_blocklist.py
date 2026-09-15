"""人工标黑（R5.3–R5.6）。

两种语义必须分开处理：

* ``item`` 级是**回溯的**：把已发布的条目立即从 portal 撤下
* ``source`` / ``domain`` / ``keyword`` / ``author`` 级是**前瞻的**：新条目进入
  审核时判定；另外提供一次性回溯扫描，把历史条目一并标黑（R5.5）

放在核心而不是 ``infohub_filter``：portal 的记录规则依赖 ``item.state``，核心
不能依赖一个可选模块才能保证访问控制正确（ADR-009）。

扩展新的标黑类型（R5.6）
-----------------------
1. 在 ``block_type`` 上 ``_selection_add`` 加值
2. 加一个 ``_blocklist_domain_<类型名>`` 方法，返回该条黑名单对应的
   ``infohub.item`` domain

不需要改动 ``_match_items``。
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Domain

_logger = logging.getLogger(__name__)


class InfohubBlocklist(models.Model):
    _name = "infohub.blocklist"
    _description = "InfoHub 黑名单"
    _order = "create_date desc"

    block_type = fields.Selection(
        [
            ("item", "单条条目"),
            ("source", "整个来源"),
            ("domain", "域名"),
            ("keyword", "关键词"),
            ("author", "作者"),
        ],
        string="类型",
        required=True,
        default="keyword",
    )
    value = fields.Char(
        string="值",
        help="域名 / 关键词 / 作者名。域名做精确主机名匹配，关键词与作者做包含匹配。",
    )
    item_id = fields.Many2one("infohub.item", string="条目", ondelete="cascade")
    source_id = fields.Many2one("infohub.source", string="来源", ondelete="cascade")

    reason = fields.Text(string="原因")
    user_id = fields.Many2one(
        "res.users",
        string="操作人",
        default=lambda self: self.env.user,
        readonly=True,
    )
    active = fields.Boolean(string="生效", default=True)

    matched_count = fields.Integer(
        string="已标黑条目数", compute="_compute_matched_count"
    )

    #: 需要 value 的类型必须填 value；需要外键的类型必须填外键
    _value_required = models.Constraint(
        """CHECK(
            (block_type = 'item' AND item_id IS NOT NULL)
            OR (block_type = 'source' AND source_id IS NOT NULL)
            OR (block_type IN ('domain', 'keyword', 'author') AND value IS NOT NULL)
            OR block_type NOT IN ('item', 'source', 'domain', 'keyword', 'author')
        )""",
        "该标黑类型缺少必要的目标或值。",
    )

    # ==================================================================
    # 展示
    # ==================================================================
    @api.depends("block_type", "value", "item_id", "source_id")
    def _compute_display_name(self):
        labels = dict(self._fields["block_type"]._description_selection(self.env))
        for entry in self:
            target = (
                entry.value
                or entry.item_id.title
                or entry.source_id.display_name
                or _("未指定")
            )
            entry.display_name = (
                f"{labels.get(entry.block_type, entry.block_type)}：{target}"
            )

    def _compute_matched_count(self):
        for entry in self:
            domain = entry._domain()
            entry.matched_count = (
                self.env["infohub.item"].search_count(domain)
                if not domain.is_false()
                else 0
            )

    # ==================================================================
    # 各类型的 domain
    # ==================================================================
    def _domain(self):
        """本条黑名单对应的条目 domain。

        按 ``_blocklist_domain_<类型>`` 的方法名约定分发，卫星模块加新类型时
        只需加对应方法。
        """
        self.ensure_one()
        handler = getattr(self, f"_blocklist_domain_{self.block_type}", None)
        if handler is None:
            _logger.warning(
                "InfoHub: 标黑类型 %s 没有对应的 _blocklist_domain_%s 实现，已忽略",
                self.block_type,
                self.block_type,
            )
            return Domain.FALSE
        return handler()

    def _blocklist_domain_item(self):
        if not self.item_id:
            return Domain.FALSE
        return Domain("id", "=", self.item_id.id)

    def _blocklist_domain_source(self):
        if not self.source_id:
            return Domain.FALSE
        return Domain("source_id", "=", self.source_id.id)

    def _blocklist_domain_domain(self):
        """域名匹配：精确主机名，或其子域名。

        用物化的 ``url_host`` 而不是对 ``url`` 做 ilike，避免 ``cnn.com``
        误伤 ``notcnn.com.evil.org``。
        """
        host = (self.value or "").strip().lower().lstrip(".")
        if not host:
            return Domain.FALSE
        return Domain("url_host", "=", host) | Domain("url_host", "=like", f"%.{host}")

    def _blocklist_domain_keyword(self):
        keyword = (self.value or "").strip()
        if not keyword:
            return Domain.FALSE
        return Domain("title", "ilike", keyword) | Domain(
            "content_text", "ilike", keyword
        )

    def _blocklist_domain_author(self):
        author = (self.value or "").strip()
        if not author:
            return Domain.FALSE
        return Domain("author_name", "ilike", author)

    # ==================================================================
    # 匹配与应用
    # ==================================================================
    @api.model
    def _active_domain(self):
        """全部生效黑名单的并集 domain。"""
        entries = self.search([])
        if not entries:
            return Domain.FALSE
        domains = [entry._domain() for entry in entries]
        domains = [d for d in domains if not d.is_false()]
        if not domains:
            return Domain.FALSE
        return Domain.OR(domains)

    @api.model
    def _match_items(self, items):
        """从给定条目中筛出命中黑名单的（前瞻判定，R5.4）。

        在内存中筛，避免为每批新条目再打一次数据库。
        """
        if not items:
            return items.browse()
        domain = self._active_domain()
        if domain.is_false():
            return items.browse()
        return items.filtered_domain(list(domain))

    def action_apply_retroactively(self):
        """回溯扫描历史条目并标黑（R5.5）。

        ``item`` 级本身就是回溯的；其余类型默认只对新条目生效，需要显式触发
        本动作才会处理历史。
        """
        blocked_total = self.env["infohub.item"].browse()
        for entry in self:
            domain = entry._domain()
            if domain.is_false():
                continue
            items = self.env["infohub.item"].search(
                domain & Domain("state", "!=", "blocked")
            )
            if items:
                items.write(
                    {
                        "state": "blocked",
                        "moderation_note": _(
                            "命中黑名单：%s", entry.display_name
                        ),
                    }
                )
                blocked_total |= items
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "info",
                "message": _("已回溯标黑 %s 条条目。", len(blocked_total)),
                "sticky": False,
            },
        }

    # ==================================================================
    # 写入钩子
    # ==================================================================
    @api.model_create_multi
    def create(self, vals_list):
        entries = super().create(vals_list)
        # item 级标黑天然是回溯的：建了就要立刻把条目撤下（R5.3）
        item_entries = entries.filtered(
            lambda entry: entry.block_type == "item" and entry.item_id
        )
        if item_entries:
            item_entries.item_id.filtered(
                lambda item: item.state != "blocked"
            ).write({"state": "blocked"})
        return entries

    @api.constrains("block_type", "value")
    def _check_value(self):
        for entry in self:
            if entry.block_type in ("domain", "keyword", "author"):
                if not (entry.value or "").strip():
                    raise ValidationError(
                        _("「%s」类型的黑名单必须填写值。", entry.block_type)
                    )

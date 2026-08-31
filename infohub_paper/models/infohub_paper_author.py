"""论文作者。

独立建模而不是在论文上存一个字符串，是为了跨条目复用与按作者检索（R11.4）——
"这位作者最近发了什么"是论文场景的核心查询。

作者消歧是个难题（同名、缩写、中间名、姓名顺序），本模块只做**保守的**归一化：
去空白、压缩空格、统一大小写形态后比对。不做启发式合并——把两位同名作者错并成
一个人，比不合并更糟。需要精确消歧时应接 ORCID（已留字段）。
"""

import re

from odoo import api, fields, models

#: 归一化时压缩的空白
_WS_RE = re.compile(r"\s+")


def normalize_author_name(raw):
    """作者名的比对键。

    只做保守处理：压缩空白、去首尾标点、转小写。不动姓名顺序、不展开缩写。
    """
    if not raw:
        return None
    text = _WS_RE.sub(" ", str(raw)).strip(" .,;")
    return text.lower() or None


class InfohubPaperAuthor(models.Model):
    _name = "infohub.paper.author"
    _description = "InfoHub 论文作者"
    _order = "name"

    name = fields.Char(string="姓名", required=True, index="trigram")
    name_normalized = fields.Char(
        string="姓名（归一化）",
        index=True,
        readonly=True,
        help="压缩空白、转小写后的形式，用于去重比对。",
    )
    orcid = fields.Char(
        string="ORCID",
        index=True,
        help="有 ORCID 时才能做可靠的作者消歧。当前的来源多不提供。",
    )
    affiliation = fields.Char(string="机构")
    paper_ids = fields.Many2many(
        "infohub.paper",
        "infohub_paper_author_rel",
        "author_id",
        "paper_id",
        string="论文",
    )
    paper_count = fields.Integer(string="论文数", compute="_compute_paper_count")

    _name_uniq = models.UniqueIndex(
        "(name_normalized) WHERE name_normalized IS NOT NULL",
        "同名作者已存在。",
    )

    def _compute_paper_count(self):
        counts = {}
        if self.ids:
            counts = {
                author.id: count
                for author, count in self.env["infohub.paper"]._read_group(
                    [("author_ids", "in", self.ids)],
                    groupby=["author_ids"],
                    aggregates=["__count"],
                )
            }
        for author in self:
            author.paper_count = counts.get(author.id, 0)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if "name" in vals:
                vals["name_normalized"] = normalize_author_name(vals.get("name"))
        return super().create(vals_list)

    def write(self, vals):
        if "name" in vals:
            vals["name_normalized"] = normalize_author_name(vals.get("name"))
        return super().write(vals)

    @api.model
    def resolve(self, names):
        """把作者名列表解析成记录集，缺的自动创建。保持传入顺序。

        一次查询解析全部，不在循环里逐个查（N+1）。
        """
        cleaned = []
        seen = set()
        for name in names or []:
            key = normalize_author_name(name)
            if not key or key in seen:
                continue
            seen.add(key)
            cleaned.append((key, _WS_RE.sub(" ", str(name)).strip(" .,;")))

        if not cleaned:
            return self.browse()

        existing = self.search([("name_normalized", "in", [k for k, _ in cleaned])])
        by_key = {author.name_normalized: author for author in existing}

        missing = [
            {"name": display, "name_normalized": key}
            for key, display in cleaned
            if key not in by_key
        ]
        if missing:
            for author in self.create(missing):
                by_key[author.name_normalized] = author

        result = self.browse()
        for key, _display in cleaned:
            author = by_key.get(key)
            if author:
                result |= author
        return result

    def action_view_papers(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.name,
            "res_model": "infohub.paper",
            "view_mode": "list,form",
            "domain": [("author_ids", "in", self.ids)],
        }

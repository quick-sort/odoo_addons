"""期刊。

独立建模以便跨条目复用与按期刊检索（R11.4）。
"""

import re

from odoo import api, fields, models

_WS_RE = re.compile(r"\s+")


def normalize_journal_name(raw):
    if not raw:
        return None
    return (_WS_RE.sub(" ", str(raw)).strip(" .,;") or "").lower() or None


class InfohubJournal(models.Model):
    _name = "infohub.journal"
    _description = "InfoHub 期刊"
    _order = "name"

    name = fields.Char(string="名称", required=True, index="trigram")
    name_normalized = fields.Char(string="名称（归一化）", index=True, readonly=True)
    issn = fields.Char(string="ISSN", index=True)
    publisher = fields.Char(string="出版方")
    homepage = fields.Char(string="主页")
    paper_ids = fields.One2many("infohub.paper", "journal_id", string="论文")
    paper_count = fields.Integer(string="论文数", compute="_compute_paper_count")

    _name_uniq = models.UniqueIndex(
        "(name_normalized) WHERE name_normalized IS NOT NULL",
        "同名期刊已存在。",
    )

    def _compute_paper_count(self):
        counts = {}
        if self.ids:
            counts = {
                journal.id: count
                for journal, count in self.env["infohub.paper"]._read_group(
                    [("journal_id", "in", self.ids)],
                    groupby=["journal_id"],
                    aggregates=["__count"],
                )
            }
        for journal in self:
            journal.paper_count = counts.get(journal.id, 0)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if "name" in vals:
                vals["name_normalized"] = normalize_journal_name(vals.get("name"))
        return super().create(vals_list)

    def write(self, vals):
        if "name" in vals:
            vals["name_normalized"] = normalize_journal_name(vals.get("name"))
        return super().write(vals)

    @api.model
    def resolve(self, name):
        """按名称取期刊，没有就创建。"""
        key = normalize_journal_name(name)
        if not key:
            return self.browse()
        journal = self.search([("name_normalized", "=", key)], limit=1)
        if journal:
            return journal
        return self.create({"name": _WS_RE.sub(" ", str(name)).strip(" .,;")})

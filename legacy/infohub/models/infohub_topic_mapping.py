"""外部分类码到学科的映射。

这张表是"接入新学科领域只加数据、不改代码"（R4.5）的关键。没有它，每接一个
新学科源都要在代码里写死一批 if/elif。

各渠道模块以数据文件带入自己的映射：``infohub_arxiv`` 带 arXiv 分类码
（cs.LG、math.AP……），将来 ``infohub_pubmed`` 带 MeSH。

映射按 ``provider`` 区分作用域，因为同一个编码在不同来源方可能含义不同
（ADR-014：学科树是共享的，编码映射是各来源方专有的）。
"""

from odoo import api, fields, models


class InfohubTopicMapping(models.Model):
    _name = "infohub.topic.mapping"
    _description = "InfoHub 学科映射"
    _order = "provider, external_code"

    provider = fields.Char(
        string="来源",
        required=True,
        index=True,
        help="来源方标识，与 infohub.source.provider 的取值一致，例如 arxiv。",
    )
    external_code = fields.Char(
        string="外部编码",
        required=True,
        index=True,
        help="来源方使用的分类码，例如 cs.LG。",
    )
    external_name = fields.Char(string="外部名称", help="来源方对该编码的原文描述。")
    topic_id = fields.Many2one(
        "infohub.topic",
        string="对应学科",
        required=True,
        ondelete="cascade",
        index=True,
    )

    _code_uniq = models.Constraint(
        "UNIQUE(provider, external_code)",
        "同一来源下的外部编码不能重复。",
    )

    @api.depends("provider", "external_code")
    def _compute_display_name(self):
        for mapping in self:
            mapping.display_name = f"[{mapping.provider}] {mapping.external_code}"

    def resolve(self, provider, codes):
        """把一批外部编码解析成学科记录集。

        供 classifier 使用。一次查询解析全部编码，不要在循环里逐个查。

        :param str provider: 来源方标识
        :param codes: 外部编码的可迭代对象
        :return: ``infohub.topic`` 记录集
        """
        codes = [code for code in (codes or []) if code]
        if not codes:
            return self.env["infohub.topic"]
        mappings = self.search(
            [("provider", "=", provider), ("external_code", "in", codes)]
        )
        return mappings.topic_id

"""论文介质载荷表。

继承 ``infohub.medium.payload``，与 ``infohub.item`` 一对一（唯一约束由抽象基类提供）。
介质特有字段放在这里而不是核心条目表上（ADR-005）：核心表不随介质数量膨胀，卸载本
模块时这张表整体消失，不留孤儿列。

DOI 归一化
----------
``doi_normalized`` 是去重用的规范形式：去掉 ``https://doi.org/`` 前缀、去掉
``doi:`` 前缀、转小写、去空白。DOI 规范里前缀（10.xxxx）大小写敏感、后缀不敏感，
但实践中登记机构对后缀大小写也不一致，所以整体转小写是业界通行的折中。
"""

import re

from odoo import _, api, fields, models

#: DOI 匹配。DOI 规范只要求 10. 开头 + 注册者编号 + / + 后缀，后缀几乎什么字符都能用，
#: 所以匹配得宽、修剪得严：先抓到空白与 HTML 敏感字符为止，再在 Python 里
#: 截断非 ASCII、剥掉尾部标点。
#: 只用正则做右边界很难写对——最初的版本漏掉了中文标点，
#: "见 10.1038/xxx。" 会把句号一起吞进去，导致同一个 DOI 算成两个。
DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s<>&\"']+)", re.IGNORECASE)

#: DOI 尾部需要剥掉的标点，含中英文
DOI_TRAILING = ".,;:!?)]}>*\u201d\u2019\u3002\uff0c\uff1b\uff1a\uff09\u3011\u300b\u3001\uff01\uff1f"

#: arXiv ID：新格式 2401.12345(v2)，旧格式 math.AP/0611800
ARXIV_NEW_RE = re.compile(r"\b(\d{4}\.\d{4,5})(v\d+)?\b")
ARXIV_OLD_RE = re.compile(r"\b([a-z-]+(?:\.[A-Z]{2})?/\d{7})(v\d+)?\b")


def _truncate_at_non_ascii(text):
    """在第一个非 ASCII 字符处截断。

    DOI 后缀按规范只使用 ASCII 可打印字符，所以遇到中文等字符就说明 DOI 已经结束、
    后面是正文了。
    """
    for index, char in enumerate(text):
        if ord(char) > 127:
            return text[:index]
    return text


def normalize_doi(raw):
    """把各种写法的 DOI 归一成 ``10.xxxx/yyyy`` 小写形式。

    :return: 归一化后的 DOI，认不出来则返回 None
    """
    if not raw:
        return None
    match = DOI_RE.search(str(raw).strip())
    if not match:
        return None
    doi = _truncate_at_non_ascii(match.group(1)).rstrip(DOI_TRAILING)
    if "/" not in doi or doi.endswith("/"):
        # 截断后只剩前缀，说明原文里 DOI 是不完整的
        return None
    return doi.lower()


def normalize_arxiv_id(raw):
    """把 arXiv ID 归一成不带版本号的形式。

    去掉版本号是有意的：v1 和 v3 是同一篇论文，应该收敛为一条。
    """
    if not raw:
        return None
    text = str(raw).strip()
    text = re.sub(r"^(arxiv:)", "", text, flags=re.IGNORECASE)
    for pattern in (ARXIV_NEW_RE, ARXIV_OLD_RE):
        match = pattern.search(text)
        if match:
            return match.group(1)
    return None


class InfohubPaper(models.Model):
    _name = "infohub.paper"
    _inherit = "infohub.medium.payload"
    _description = "InfoHub 论文"
    _order = "id desc"
    _rec_name = "display_name"

    # ------------------------------------------------------------------
    # 身份
    # ------------------------------------------------------------------
    doi = fields.Char(string="DOI", help="原始写法，保留来源方给的形式。")
    doi_normalized = fields.Char(
        string="DOI（归一化）",
        index=True,
        readonly=True,
        help="去掉前缀、转小写后的形式，用于跨源去重。",
    )
    arxiv_id = fields.Char(
        string="arXiv ID",
        index=True,
        help="不含版本号：v1 与 v3 是同一篇论文，应收敛为一条。",
    )

    # ------------------------------------------------------------------
    # 内容
    # ------------------------------------------------------------------
    abstract = fields.Text(string="摘要")
    author_ids = fields.Many2many(
        "infohub.paper.author",
        "infohub_paper_author_rel",
        "paper_id",
        "author_id",
        string="作者",
    )
    author_names = fields.Char(
        string="作者列表",
        compute="_compute_author_names",
        store=True,
        help="按顺序拼接的作者名，供列表展示与搜索，避免每行都联表。",
    )
    journal_id = fields.Many2one(
        "infohub.journal", string="期刊", ondelete="set null", index=True
    )
    volume = fields.Char(string="卷")
    issue = fields.Char(string="期")
    pages = fields.Char(string="页")
    published_version = fields.Selection(
        [
            ("preprint", "预印本"),
            ("accepted", "已接收"),
            ("published", "已发表"),
        ],
        string="发表阶段",
        default="preprint",
        index=True,
    )
    citation_count = fields.Integer(string="引用数")

    #: 只存链接，不下载文件（R11.2）
    pdf_url = fields.Char(
        string="PDF 链接",
        help="只保存链接，不下载文件、不进附件库。",
    )

    # ------------------------------------------------------------------
    # 便捷字段（从条目侧借来，省去列表页联表）
    # ------------------------------------------------------------------
    title = fields.Char(related="item_id.title", store=True, string="标题", readonly=True)
    url = fields.Char(related="item_id.url", string="原文链接", readonly=True)
    published_at = fields.Datetime(
        related="item_id.published_at", store=True, string="发布时间", readonly=True
    )
    source_id = fields.Many2one(
        related="item_id.source_id", store=True, string="来源", readonly=True
    )
    state = fields.Selection(related="item_id.state", store=True, string="状态", readonly=True)
    topic_ids = fields.Many2many(related="item_id.topic_ids", string="学科", readonly=True)

    #: 同一个 DOI 只应有一条论文记录。用部分唯一索引：DOI 为空的预印本不受约束。
    _doi_uniq = models.UniqueIndex(
        "(doi_normalized) WHERE doi_normalized IS NOT NULL",
        "该 DOI 的论文已存在。",
    )
    _arxiv_uniq = models.UniqueIndex(
        "(arxiv_id) WHERE arxiv_id IS NOT NULL",
        "该 arXiv ID 的论文已存在。",
    )

    # ==================================================================
    @api.depends("author_ids", "author_ids.name")
    def _compute_author_names(self):
        for paper in self:
            paper.author_names = ", ".join(paper.author_ids.mapped("name")) or False

    @api.depends("title", "doi", "arxiv_id")
    def _compute_display_name(self):
        for paper in self:
            label = paper.title or paper.doi or paper.arxiv_id or _("未命名论文")
            paper.display_name = label

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._normalize_identifiers(vals)
        return super().create(vals_list)

    def write(self, vals):
        if "doi" in vals or "arxiv_id" in vals:
            self._normalize_identifiers(vals)
        return super().write(vals)

    @api.model
    def _normalize_identifiers(self, vals):
        """入库前归一化 DOI 与 arXiv ID。"""
        if "doi" in vals:
            vals["doi_normalized"] = normalize_doi(vals.get("doi"))
        if "arxiv_id" in vals:
            vals["arxiv_id"] = normalize_arxiv_id(vals.get("arxiv_id"))
        return vals

    def action_open_pdf(self):
        self.ensure_one()
        if not self.pdf_url:
            return False
        return {"type": "ir.actions.act_url", "url": self.pdf_url, "target": "new"}

    def action_open_doi(self):
        self.ensure_one()
        if not self.doi_normalized:
            return False
        return {
            "type": "ir.actions.act_url",
            "url": f"https://doi.org/{self.doi_normalized}",
            "target": "new",
        }

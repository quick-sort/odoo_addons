"""网页采集的选择器配置。

这个模型是本模块的全部价值所在：**接入一个新站点是加一条记录，不是写一个模块**
（ADR-018 / N10）。

选择器在保存时就编译校验
------------------------
和 ``infohub_filter`` 的正则同样的道理：坏选择器不该跑到采集流水线里才炸。用
soupsieve 编译（BeautifulSoup 的 ``select()`` 底层就是它），编译失败直接拒绝保存。
"""

import soupsieve

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

#: 选择器字段名 -> 界面标签，用于校验时给出可读的错误定位
SELECTOR_FIELDS = {
    "item_link_selector": "条目链接选择器",
    "next_link_selector": "下一页选择器",
    "title_selector": "标题选择器",
    "content_selector": "正文选择器",
    "summary_selector": "摘要选择器",
    "author_selector": "作者选择器",
    "date_selector": "日期选择器",
}


def compile_selector(selector):
    """编译 CSS 选择器，返回 soupsieve 的编译结果。

    :raise ValueError: 选择器语法非法
    """
    return soupsieve.compile(selector)


class InfohubWebProfile(models.Model):
    _name = "infohub.web.profile"
    _description = "InfoHub 网页采集配置"
    _order = "name"

    name = fields.Char(string="名称", required=True)
    active = fields.Boolean(string="启用", default=True)
    notes = fields.Text(
        string="备注",
        help="记下这个站点的结构特点、坑在哪、什么时候需要复查选择器。",
    )

    # ==================================================================
    # 列表页
    # ==================================================================
    list_url_template = fields.Char(
        string="列表页 URL",
        help=(
            "留空则用源的「端点」。分页方式为「页码参数」时，用 {page} 作为占位符，"
            "例如 https://example.com/blog?page={page}"
        ),
    )
    item_link_selector = fields.Char(
        string="条目链接选择器",
        required=True,
        help="CSS 选择器，选中列表页里指向条目的 <a>，例如 article h2 a",
    )
    link_attribute = fields.Char(
        string="链接属性",
        default="href",
        required=True,
        help="从选中元素的哪个属性取链接。通常是 href。",
    )
    same_host_only = fields.Boolean(
        string="仅同域链接",
        default=True,
        help=(
            "只跟随与列表页同域名的链接。既避免抓到站外的无关内容，也降低被列表页上的"
            "第三方链接带去请求任意地址的风险。"
        ),
    )

    # ==================================================================
    # 分页
    # ==================================================================
    pagination_mode = fields.Selection(
        [
            ("none", "不分页"),
            ("page_param", "页码参数"),
            ("next_link", "下一页链接"),
        ],
        string="分页方式",
        default="none",
        required=True,
    )
    next_link_selector = fields.Char(
        string="下一页选择器",
        help="分页方式为「下一页链接」时，选中指向下一页的 <a>。",
    )
    page_start = fields.Integer(string="起始页码", default=1)
    page_step = fields.Integer(string="页码步长", default=1)
    max_pages = fields.Integer(
        string="单轮最大页数",
        default=3,
        help="一轮抓取最多翻几页。首次接入时可以调大做一次回填，之后调回小值。",
    )

    # ==================================================================
    # 详情页
    # ==================================================================
    detail_mode = fields.Selection(
        [
            ("fetch", "抓取详情页"),
            ("list_only", "仅用列表页"),
        ],
        string="详情来源",
        default="fetch",
        required=True,
        help=(
            "「仅用列表页」适用于列表页本身就带全文的站点，可以省掉每条一次请求。"
            "此时下面的选择器作用在列表项的片段上，而不是详情页。"
        ),
    )
    title_selector = fields.Char(
        string="标题选择器", help="留空则退回读页面的 title 标签。"
    )
    content_selector = fields.Char(
        string="正文选择器",
        help="选中正文容器，例如 article .post-content。留空则不提取正文。",
    )
    summary_selector = fields.Char(string="摘要选择器")
    author_selector = fields.Char(string="作者选择器")
    date_selector = fields.Char(
        string="日期选择器",
        help="选中含发布时间的元素。优先读它的 datetime 属性，没有则读文本。",
    )
    date_format = fields.Char(
        string="日期格式",
        help=(
            "strptime 格式串，例如 %Y-%m-%d。留空则用 dateutil 自动识别"
            "（能认大多数常见写法，但中文日期需要显式给格式）。"
        ),
    )
    strip_selectors = fields.Text(
        string="剔除选择器",
        help=(
            "从正文中删除的噪声节点，一行一个 CSS 选择器。"
            "常见的有 .advertisement、.related-posts、.comments、nav、footer。"
        ),
    )

    # ==================================================================
    # 限额与预留
    # ==================================================================
    max_items_per_run = fields.Integer(
        string="单轮最大条目数",
        default=50,
        help="一轮最多抓多少个详情页。抓详情页是每条一次请求，必须设上限。",
    )
    render_js = fields.Boolean(
        string="需要 JS 渲染",
        help=(
            "预留字段，当前**尚未实现**。勾上后采集会直接报错而不是静默抓到空页面。"
            "需要 JS 渲染的站点目前请另写渠道模块。"
        ),
    )

    source_ids = fields.One2many("infohub.source", "web_profile_id", string="使用的源")
    source_count = fields.Integer(string="源数量", compute="_compute_source_count")

    _check_pages = models.Constraint(
        "CHECK(max_pages > 0 AND max_items_per_run > 0)",
        "最大页数与单轮最大条目数都必须为正数。",
    )

    # ==================================================================
    @api.depends("source_ids")
    def _compute_source_count(self):
        for profile in self:
            profile.source_count = len(profile.source_ids)

    @api.constrains(*SELECTOR_FIELDS)
    def _check_selectors(self):
        """保存时就把坏选择器挡住。"""
        for profile in self:
            for field_name, label in SELECTOR_FIELDS.items():
                selector = (profile[field_name] or "").strip()
                if not selector:
                    continue
                try:
                    compile_selector(selector)
                except Exception as exc:  # noqa: BLE001 - soupsieve 的异常类型不稳定
                    raise ValidationError(
                        _(
                            "「%(label)s」不是合法的 CSS 选择器：\n%(err)s",
                            label=label,
                            err=exc,
                        )
                    ) from exc

    @api.constrains("strip_selectors")
    def _check_strip_selectors(self):
        for profile in self:
            for selector in profile.strip_selector_list():
                try:
                    compile_selector(selector)
                except Exception as exc:  # noqa: BLE001
                    raise ValidationError(
                        _(
                            "剔除选择器 %(sel)r 不是合法的 CSS 选择器：\n%(err)s",
                            sel=selector,
                            err=exc,
                        )
                    ) from exc

    @api.constrains("pagination_mode", "next_link_selector", "list_url_template")
    def _check_pagination(self):
        for profile in self:
            if profile.pagination_mode == "next_link" and not profile.next_link_selector:
                raise ValidationError(
                    _("分页方式为「下一页链接」时必须填写下一页选择器。")
                )
            if profile.pagination_mode == "page_param":
                template = profile.list_url_template or ""
                if "{page}" not in template:
                    raise ValidationError(
                        _("分页方式为「页码参数」时，列表页 URL 必须含 {page} 占位符。")
                    )

    def strip_selector_list(self):
        """把剔除选择器按行拆成列表。"""
        self.ensure_one()
        if not self.strip_selectors:
            return []
        return [line.strip() for line in self.strip_selectors.splitlines() if line.strip()]

    def list_url(self, source, page=None):
        """算出列表页 URL。"""
        self.ensure_one()
        template = self.list_url_template or source.endpoint or ""
        if self.pagination_mode == "page_param" and page is not None:
            return template.replace("{page}", str(page))
        # 不分页时模板里若仍留着占位符，用起始页码填掉，避免请求到字面量 {page}
        return template.replace("{page}", str(self.page_start or 1))

"""在 transport 维度上加 ``arxiv_api``，并把抓取任务路由到专用限速通道。

关于这里的 if 分支
------------------
``_queue_channel()`` 里出现了 ``if self.transport == "arxiv_api"``。项目约束说"调用方
不得出现来源判断分支"，但那条约束针对的是**核心与流水线调用方**：它们必须靠 component
解析而不是硬编码分支。这里是**卫星模块在自己的模型扩展里判断"这个源是不是我的"**，
是 Odoo ``_inherit`` 覆盖的标准形态——不加这个守卫就会劫持所有源的通道。

不过这确实暴露了核心的一个可改进点：``_queue_channel()`` 没有委托给 transport
component，而"用哪个队列通道"本质上是**传输方式**的属性。已作为复核点发现记录在
progress.md，是否改核心留待决定；当前实现不需要改核心即可正确工作。
"""

from odoo import fields, models

#: 本模块使用的 queue_job 通道。容量需在 odoo.conf 里配成 1，见模块说明。
ARXIV_CHANNEL = "root.infohub.arxiv"

#: arXiv 建议的最小请求间隔（秒）
ARXIV_MIN_INTERVAL = 3.0


class InfohubSource(models.Model):
    _inherit = "infohub.source"

    transport = fields.Selection(
        selection_add=[("arxiv_api", "arXiv API")],
        ondelete={"arxiv_api": "cascade"},
    )
    provider = fields.Selection(
        selection_add=[("arxiv", "arXiv")],
        ondelete={"arxiv": "cascade"},
    )

    arxiv_max_results = fields.Integer(
        string="每页条数",
        default=100,
        help=(
            "arXiv API 单次请求返回的条数。官方建议不超过 100（上限 2000，"
            "但大页容易超时）。"
        ),
    )
    arxiv_max_pages = fields.Integer(
        string="单轮最大页数",
        default=10,
        help="一轮抓取最多翻几页，避免首次全量抓取时一个任务跑太久。",
    )

    def _queue_channel(self):
        """arXiv 源走专用限速通道。

        见模块文档字符串关于这个 if 分支的说明。
        """
        self.ensure_one()
        if self.transport == "arxiv_api":
            return ARXIV_CHANNEL
        return super()._queue_channel()

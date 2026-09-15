"""信息源 —— 同时是 component 的 collection。

三轴组合（ADR-002）::

    infohub.source = medium × transport × provider
                       介质      传输       来源

三个维度各自由卫星模块用 ``_selection_add`` 扩展。核心**不含任何来源判断
分支**：所有可变行为都通过 component 解析（ADR-001）。

组合的合法性由"可解析性"定义（ADR-008）：不维护三元组白名单，而是在约束里
尝试解析三个维度对应的 component，任一解析不到即拒绝。这样装上新模块就自动
放开新组合，没有第二处需要同步维护。
"""

import logging
from contextlib import contextmanager

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.addons.component.exception import (
    NoComponentError,
    RegistryNotReadyError,
    SeveralComponentError,
)
from odoo.exceptions import UserError, ValidationError

from ..url_guard import allow_private_from_env, assert_url_allowed

_logger = logging.getLogger(__name__)

#: 采集流水线依赖的三个必选 usage。缺任一即认为组合非法。
REQUIRED_USAGES = ("transport", "medium", "mapper")

_INTERVAL_FACTORS = {
    "minutes": lambda n: relativedelta(minutes=n),
    "hours": lambda n: relativedelta(hours=n),
    "days": lambda n: relativedelta(days=n),
    "weeks": lambda n: relativedelta(weeks=n),
}


class InfohubSource(models.Model):
    _name = "infohub.source"
    _description = "InfoHub 信息源"
    _inherit = ["collection.base", "mail.thread"]
    _order = "name"

    name = fields.Char(string="名称", required=True, tracking=True)
    active = fields.Boolean(string="启用", default=True, tracking=True)

    # ------------------------------------------------------------------
    # 三轴
    # ------------------------------------------------------------------
    medium = fields.Selection(
        selection=[("article", "文章")],
        string="介质",
        required=True,
        default="article",
        tracking=True,
        help="决定条目的字段语义与去重身份算法。由介质模块扩展。",
    )
    transport = fields.Selection(
        selection=[("http", "HTTP")],
        string="传输",
        required=True,
        tracking=True,
        help=(
            "决定怎么拿到字节、怎么做增量。由传输模块扩展。"
            "注意核心只带通用 HTTP 传输，且核心不提供与之配套的通用 mapper——"
            "要抓 RSS 或网页请安装 infohub_rss / infohub_web。"
        ),
    )
    provider = fields.Selection(
        selection=[("generic", "通用")],
        string="来源",
        required=True,
        default="generic",
        tracking=True,
        help=(
            "决定该来源特有的字段映射。必填且默认为「通用」——留空会导致多个 "
            "mapper 同时命中并抛 SeveralComponentError（ADR-007）。"
        ),
    )

    endpoint = fields.Char(
        string="端点",
        help="源的 URL 或 API 端点。只允许 http/https，且不能指向内网地址。",
    )
    credential_id = fields.Many2one(
        "infohub.credential",
        string="凭证",
        ondelete="restrict",
        help="需要认证的源在此关联凭证。凭证仅管理员可读。",
    )
    access_level = fields.Selection(
        [("public", "公开"), ("internal", "内部")],
        string="可见范围",
        required=True,
        default="public",
        help="internal 的源及其条目对 portal 读者不可见，为将来接入付费或内部源预留。",
    )

    # ------------------------------------------------------------------
    # 调度
    # ------------------------------------------------------------------
    interval_number = fields.Integer(string="间隔", required=True, default=1)
    interval_type = fields.Selection(
        [
            ("minutes", "分钟"),
            ("hours", "小时"),
            ("days", "天"),
            ("weeks", "周"),
        ],
        string="间隔单位",
        required=True,
        default="hours",
    )
    next_run_at = fields.Datetime(string="下次抓取", index=True)
    last_run_at = fields.Datetime(string="上次抓取", readonly=True)
    min_request_interval = fields.Float(
        string="最小请求间隔（秒）",
        default=0.0,
        help=(
            "同一次抓取内两次出网请求之间的最小间隔，用于遵守来源方的限速要求。"
            "注意这只约束单次任务内部；跨任务的全局限速要靠专用 queue_job 通道"
            "（见 ADR-012）。"
        ),
    )

    #: 增量游标。形态因传输而异（ETag / Last-Modified / since_id / 最后发布时间），
    #: 所以用 Json 而不是一堆专用字段。
    cursor_state = fields.Json(string="增量游标", readonly=True)

    # ------------------------------------------------------------------
    # 健康状况
    # ------------------------------------------------------------------
    error_count = fields.Integer(string="连续失败次数", readonly=True, copy=False)
    last_error = fields.Text(string="最后一次错误", readonly=True, copy=False)
    max_errors = fields.Integer(
        string="失败停用阈值",
        default=10,
        help="连续失败达到该次数后自动停用本源，并在沟通栏留言。设为 0 表示不自动停用。",
    )

    # ------------------------------------------------------------------
    # 分类与统计
    # ------------------------------------------------------------------
    topic_ids = fields.Many2many(
        "infohub.topic",
        "infohub_source_topic_rel",
        "source_id",
        "topic_id",
        string="默认学科",
        help="本源产出的条目会自动继承这些学科。",
    )
    default_tag_ids = fields.Many2many(
        "infohub.tag",
        "infohub_source_tag_rel",
        "source_id",
        "tag_id",
        string="默认标签",
    )
    is_recommended = fields.Boolean(
        string="推荐订阅",
        help="勾选后，新注册的读者会自动订阅本源。",
    )

    item_ids = fields.One2many("infohub.item", "source_id", string="条目")
    item_count = fields.Integer(string="条目数", compute="_compute_item_count")
    run_ids = fields.One2many("infohub.source.run", "source_id", string="抓取日志")

    _check_interval_positive = models.Constraint(
        "CHECK(interval_number > 0)",
        "抓取间隔必须为正数。",
    )

    # ==================================================================
    # 计算与约束
    # ==================================================================
    def _compute_item_count(self):
        counts = {}
        if self.ids:
            counts = {
                source.id: count
                for source, count in self.env["infohub.item"]._read_group(
                    [("source_id", "in", self.ids)],
                    groupby=["source_id"],
                    aggregates=["__count"],
                )
            }
        for source in self:
            source.item_count = counts.get(source.id, 0)

    @api.constrains("endpoint")
    def _check_endpoint(self):
        """SSRF 的**保存时**快速校验（N3）。

        只查 scheme、主机名存在性、字面量 IP 与已知本机名，**不做 DNS 解析**：
        在约束里发网络请求会让每次保存都阻塞在 DNS 上，而且保存时的解析结果并不能
        保证请求时相同。

        真正的防护点在发起请求时——``infohub.http`` 对每一跳都做完整解析校验。
        """
        allow_private = allow_private_from_env(self.env)
        for source in self:
            if source.endpoint:
                assert_url_allowed(
                    source.endpoint, allow_private=allow_private, resolve=False
                )

    @api.constrains("medium", "transport", "provider")
    def _check_composition(self):
        """组合合法性 = 三个必选 usage 都能解析出唯一 component（ADR-008）。"""
        for source in self:
            for usage in REQUIRED_USAGES:
                source._resolve_component_or_raise(usage)

    def _resolve_component_or_raise(self, usage):
        """解析某个 usage 的 component，失败时给出可操作的错误信息。"""
        self.ensure_one()
        try:
            with self.work_on() as work:
                return work.component(usage=usage)
        except RegistryNotReadyError:
            # 模块安装过程中 component 注册表可能还没建好（例如数据文件正在
            # 创建源记录）。此时跳过校验，而不是让安装失败。
            _logger.debug(
                "InfoHub: component 注册表未就绪，跳过对源 %s 的 %s 校验",
                self.display_name,
                usage,
            )
            return None
        except NoComponentError as exc:
            raise ValidationError(
                _(
                    "组合（介质=%(medium)s，传输=%(transport)s，来源=%(provider)s）"
                    "缺少 %(usage)s 实现，请确认已安装提供该实现的模块。",
                    medium=self.medium,
                    transport=self.transport,
                    provider=self.provider,
                    usage=usage,
                )
            ) from exc
        except SeveralComponentError as exc:
            # 通常意味着某个卫星模块的 _component_match 没有保证唯一性
            raise ValidationError(
                _(
                    "组合（介质=%(medium)s，传输=%(transport)s，来源=%(provider)s）"
                    "的 %(usage)s 匹配到多个实现，这是模块设计错误：\n%(detail)s",
                    medium=self.medium,
                    transport=self.transport,
                    provider=self.provider,
                    usage=usage,
                    detail=exc,
                )
            ) from exc

    # ==================================================================
    # Component 入口
    # ==================================================================
    @contextmanager
    def work_on(self, model_name=None, **kwargs):
        """把源记录注入 WorkContext。

        三个维度的 ``_component_match`` 都从 ``work.source`` 读取判断依据，
        所以这个注入是三轴多态的前提。
        """
        self.ensure_one()
        kwargs.setdefault("source", self)
        with super().work_on(model_name or "infohub.item", **kwargs) as work:
            yield work

    # ==================================================================
    # 调度
    # ==================================================================
    def _interval_delta(self):
        self.ensure_one()
        factory = _INTERVAL_FACTORS.get(self.interval_type)
        if not factory:
            return relativedelta(hours=1)
        return factory(max(self.interval_number, 1))

    def _schedule_next_run(self, from_datetime=None):
        """安排下一次抓取时间。"""
        base = from_datetime or fields.Datetime.now()
        for source in self:
            source.next_run_at = base + source._interval_delta()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals.setdefault("next_run_at", fields.Datetime.now())
        return super().create(vals_list)

    def _queue_channel(self):
        """本源的 queue_job 通道。

        卫星模块可覆盖以走专用通道实现全局限速。例如 ``infohub_arxiv`` 返回
        ``root.infohub.arxiv``，配合 odoo.conf 里该通道容量 1，把所有 arXiv
        抓取串成一条队列（ADR-012）。
        """
        self.ensure_one()
        return "root.infohub"

    @api.model
    def _cron_fetch_due_sources(self, limit=200):
        """cron 入口：把到期的源逐个派成异步任务。

        cron 本身只做调度，不做抓取——否则一个慢源会拖住整轮（R2.2）。
        """
        due = self.search(
            [
                ("active", "=", True),
                "|",
                ("next_run_at", "=", False),
                ("next_run_at", "<=", fields.Datetime.now()),
            ],
            limit=limit,
            order="next_run_at asc nulls first",
        )
        due._enqueue_fetch()
        return len(due)

    def _enqueue_fetch(self):
        """派发抓取任务。

        ``identity_key`` 保证同一个源在上一轮未完成时不会被重复入队（R2.3）。
        """
        for source in self:
            source.with_delay(
                channel=source._queue_channel(),
                description=_("InfoHub 抓取：%s", source.display_name),
                identity_key=f"infohub-fetch-{source.id}",
            )._fetch()
        return True

    def action_fetch_now(self):
        """手工触发抓取（异步）。"""
        self._enqueue_fetch()
        return True

    def action_fetch_sync(self):
        """手工触发抓取（同步），用于调试。

        故意不加 ``identity_key`` 之类的保护，只在后台按钮上给管理员使用。
        """
        for source in self:
            source._fetch()
        return True

    def action_reset_cursor(self):
        """清空增量游标，下一轮将全量重抓。"""
        self.write({"cursor_state": False})
        for source in self:
            source.message_post(body=_("增量游标已清空，下次抓取将从头开始。"))
        return True

    def action_reactivate(self):
        """重新启用因连续失败被自动停用的源。"""
        self.write({"active": True, "error_count": 0, "last_error": False})
        return True

    def action_view_items(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("「%s」的条目", self.display_name),
            "res_model": "infohub.item",
            "view_mode": "list,form",
            "domain": [("source_id", "=", self.id)],
            "context": {"default_source_id": self.id},
        }

    # ==================================================================
    # 采集流水线
    # ==================================================================
    def _fetch(self):
        """采集流水线主体，也是 queue_job 的任务体。

        编排顺序：transport → mapper → medium → 去重 → 落库 → classifier →
        审核。整个方法**没有任何来源判断分支**，全部行为来自 component。

        增强（正文提取、LLM）不在这里同步执行，各自派独立任务（R10.2）。

        关于失败时的事务语义
        --------------------
        抓取失败时 queue_job 会回滚整个事务，所以失败簿记（失败计数、错误日志、
        自动停用）**必须写在独立 cursor 里**，否则会随事务一起消失——那样
        ``error_count`` 永远停在 0，R1.6 的自动停用形同虚设。见
        :meth:`_register_failure`。
        """
        self.ensure_one()
        started = fields.Datetime.now()
        try:
            created, skipped, found = self._run_pipeline()
        except Exception as exc:  # noqa: BLE001 - 任何失败都要转成源的健康状态
            self._register_failure(started, exc)
            raise
        return self._register_success(
            started, found=found, created=created, skipped=skipped
        )

    def _run_pipeline(self):
        """执行一轮抓取，返回 ``(created, skipped, found)``。"""
        self.ensure_one()
        with self.work_on() as work:
            transport = work.component(usage="transport")
            mapper = work.component(usage="mapper")
            medium = work.component(usage="medium")
            classifiers = work.many_components(usage="classifier")

            entries, cursor_state = transport.fetch()
            entries = list(entries or [])

            items = self.env["infohub.item"]
            skipped = 0
            for entry in entries:
                payload = mapper.map(entry)
                if not payload or not payload.get("title"):
                    skipped += 1
                    continue
                payload["identity_key"] = medium.identity(payload)
                item, is_new = self._upsert_item(payload)
                if not is_new:
                    skipped += 1
                    continue
                medium.store_payload(item, payload)
                for classifier in classifiers:
                    classifier.classify(item, entry)
                items |= item

            # 只有整轮成功才推进游标：失败时保留旧游标，下次重试不会漏数据
            if cursor_state is not None:
                self.cursor_state = cursor_state

            items._moderate()
            items._enqueue_enrichment()
            return len(items), skipped, len(entries)

    def _upsert_item(self, payload):
        """按同源身份与跨源身份去重后落库。

        :return: ``(item, is_new)``。已存在时 ``is_new`` 为 False，条目不被覆盖
            （来源方修订内容的处理留给后续需求，当前策略是先到先得）。
        """
        self.ensure_one()
        Item = self.env["infohub.item"]

        external_id = payload.get("external_id")
        if external_id:
            existing = Item.search(
                [("source_id", "=", self.id), ("external_id", "=", external_id)],
                limit=1,
            )
            if existing:
                return existing, False

        identity_key = payload.get("identity_key")
        if identity_key:
            # 跨源去重：同一内容经不同源进入时收敛为一条（R3.2）
            existing = Item.search([("identity_key", "=", identity_key)], limit=1)
            if existing:
                return existing, False

        return Item.create(self._item_vals(payload)), True

    def _item_vals(self, payload):
        """把归一化数据裁剪成 ``infohub.item`` 的 vals。

        mapper 允许在 payload 里放介质专用的键（由 ``medium.payload_vals``
        消费），这里按字段白名单过滤掉它们，避免 create 报未知字段。
        """
        self.ensure_one()
        Item = self.env["infohub.item"]
        vals = {
            key: value for key, value in payload.items() if key in Item._fields
        }
        vals["source_id"] = self.id
        vals.setdefault("fetched_at", fields.Datetime.now())
        if self.topic_ids:
            vals.setdefault("topic_ids", [(6, 0, self.topic_ids.ids)])
        if self.default_tag_ids:
            vals.setdefault("tag_ids", [(6, 0, self.default_tag_ids.ids)])
        return vals

    # ==================================================================
    # 健康状态
    # ==================================================================
    def _register_success(self, started, found, created, skipped):
        """成功簿记，走主事务（与本轮抓取的数据一起提交）。"""
        self.ensure_one()
        now = fields.Datetime.now()
        run = self.env["infohub.source.run"].create(
            {
                "source_id": self.id,
                "state": "done",
                "date_started": started,
                "date_finished": now,
                "item_found": found,
                "item_created": created,
                "item_skipped": skipped,
            }
        )
        self.write({"last_run_at": now, "error_count": 0, "last_error": False})
        self._schedule_next_run(now)
        return run

    def _register_failure(self, started, exc):
        """失败簿记，**走独立 cursor**。

        调用方会把异常继续抛出交给 queue_job，而 queue_job 会回滚整个事务。
        若在当前 cursor 里写失败计数，它会随事务一起消失，``error_count``
        将永远停在 0，自动停用（R1.6）永远不会触发。

        因此这里开一个新 cursor 独立提交。``with pool.cursor()`` 在正常退出时
        提交、任何情况下关闭（见 ``odoo/sql_db.py`` 的 ``BaseCursor.__exit__``）。
        """
        self.ensure_one()
        now = fields.Datetime.now()
        message = f"{type(exc).__name__}: {exc}"
        source_id = self.id

        try:
            with self.pool.cursor() as cr:
                env = self.env(cr=cr)
                source = env["infohub.source"].browse(source_id)
                if not source.exists():
                    return False

                env["infohub.source.run"].create(
                    {
                        "source_id": source_id,
                        "state": "failed",
                        "date_started": started,
                        "date_finished": now,
                        "error": message,
                    }
                )

                error_count = source.error_count + 1
                values = {
                    "last_run_at": now,
                    "error_count": error_count,
                    "last_error": message,
                }
                if source.max_errors and error_count >= source.max_errors:
                    values["active"] = False
                    source.message_post(
                        body=_(
                            "本源已连续失败 %(count)s 次，达到阈值后自动停用。"
                            "最后一次错误：%(error)s",
                            count=error_count,
                            error=message,
                        )
                    )
                    _logger.warning(
                        "InfoHub: 源 %s 连续失败 %s 次，已自动停用",
                        source.display_name,
                        error_count,
                    )
                source.write(values)
                source._schedule_next_run(now)
        except Exception:  # noqa: BLE001 - 簿记失败不能掩盖原始异常
            _logger.exception(
                "InfoHub: 记录源 %s 的失败状态时出错，原始错误：%s", source_id, message
            )
        return True

    # ==================================================================
    # 预设
    # ==================================================================
    @api.model
    def create_from_preset(self, preset):
        """按预设创建源。见 ``infohub.source.preset``。"""
        if not preset:
            raise UserError(_("请先选择一个预设。"))
        return self.create(preset._source_vals())

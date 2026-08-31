"""过滤规则。

条件 = ``condition_domain`` ∧ ``keyword_regex``，两个都可留空（留空即不限）。
动作分终结型（publish / reject）与标注型（tag / score / topic）。

关于正则的两个防护
------------------
1. **保存时校验**：``re.compile`` 失败直接拒绝保存，不让坏正则跑到采集流水线里
   才炸。
2. **限制被匹配文本的长度**：Python 的 ``re`` 没有超时机制，一个写得不好的正则
   （嵌套量词等）在长文本上可能指数级回溯，把 worker 卡死。所以只对正文的前
   ``REGEX_TEXT_LIMIT`` 个字符做匹配。这不能根治 ReDoS，但把最坏情况的输入规模
   压到了可控范围。
"""

import logging
import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.fields import Domain
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)

#: 正则只对正文的前这么多字符做匹配，见模块文档的 ReDoS 说明
REGEX_TEXT_LIMIT = 100_000

#: 试运行时取最近多少条条目做样本
DRY_RUN_SAMPLE = 200


class InfohubRule(models.Model):
    _name = "infohub.rule"
    _description = "InfoHub 过滤规则"
    _order = "sequence, id"

    name = fields.Char(string="名称", required=True)
    sequence = fields.Integer(string="顺序", default=10)
    active = fields.Boolean(string="启用", default=True)
    description = fields.Text(string="说明")

    # ------------------------------------------------------------------
    # 条件
    # ------------------------------------------------------------------
    condition_domain = fields.Text(
        string="条件 domain",
        help=(
            "对 infohub.item 的 Odoo domain，例如 "
            "[('source_id.provider', '=', 'arxiv')]。留空表示不限。"
        ),
    )
    keyword_regex = fields.Char(
        string="关键词正则",
        help=(
            "Python 正则，忽略大小写。留空表示不限。"
            "注意：只对正文的前 100000 个字符做匹配。"
        ),
    )
    regex_target = fields.Selection(
        [
            ("title", "仅标题"),
            ("content", "仅正文"),
            ("both", "标题或正文"),
        ],
        string="正则匹配范围",
        default="both",
        required=True,
    )

    # ------------------------------------------------------------------
    # 动作
    # ------------------------------------------------------------------
    action = fields.Selection(
        [
            ("tag", "打标签"),
            ("score", "调整评分"),
            ("topic", "指派学科"),
            ("publish", "直接发布"),
            ("reject", "直接拒绝"),
        ],
        string="动作",
        required=True,
        default="tag",
        help=(
            "publish / reject 是终结型：定下状态后该条目不再过后续规则。"
            "tag / score / topic 是标注型：打完标注继续，除非勾了「命中后停止」。"
        ),
    )
    tag_ids = fields.Many2many(
        "infohub.tag",
        "infohub_rule_tag_rel",
        "rule_id",
        "tag_id",
        string="要打的标签",
    )
    topic_ids = fields.Many2many(
        "infohub.topic",
        "infohub_rule_topic_rel",
        "rule_id",
        "topic_id",
        string="要指派的学科",
    )
    score_delta = fields.Float(
        string="评分增减", default=0.0, help="正数加分，负数减分。"
    )
    set_primary_topic = fields.Boolean(
        string="同时设为主学科",
        help="仅在动作为「指派学科」时有效，且只在条目还没有主学科时设置。",
    )
    stop_after = fields.Boolean(
        string="命中后停止",
        help="命中的条目不再参与后续规则的求值。终结型动作本身就会停止，不需要勾。",
    )

    hit_count = fields.Integer(
        string="累计命中", readonly=True, copy=False, help="本规则历史命中的条目数。"
    )

    _check_score_action = models.Constraint(
        "CHECK(action != 'score' OR score_delta != 0)",
        "「调整评分」动作的评分增减不能为 0。",
    )

    # ==================================================================
    # 校验
    # ==================================================================
    @api.constrains("keyword_regex")
    def _check_keyword_regex(self):
        """保存时就把坏正则挡住，不让它跑到采集流水线里才炸。"""
        for rule in self:
            if not rule.keyword_regex:
                continue
            try:
                re.compile(rule.keyword_regex, re.IGNORECASE)
            except re.error as exc:
                raise ValidationError(
                    _("正则表达式无效：%(err)s\n规则：%(name)s", err=exc, name=rule.name)
                ) from exc

    @api.constrains("condition_domain")
    def _check_condition_domain(self):
        for rule in self:
            if not rule.condition_domain:
                continue
            try:
                domain = safe_eval(rule.condition_domain)
                Domain(domain).validate(self.env["infohub.item"])
            except Exception as exc:  # noqa: BLE001 - safe_eval / domain 的异常形态很多
                raise ValidationError(
                    _("条件 domain 无效：%(err)s\n规则：%(name)s", err=exc, name=rule.name)
                ) from exc

    @api.constrains("action", "tag_ids", "topic_ids")
    def _check_action_payload(self):
        for rule in self:
            if rule.action == "tag" and not rule.tag_ids:
                raise ValidationError(_("「打标签」动作必须指定至少一个标签。"))
            if rule.action == "topic" and not rule.topic_ids:
                raise ValidationError(_("「指派学科」动作必须指定至少一个学科。"))

    # ==================================================================
    # 求值
    # ==================================================================
    def _domain(self):
        """规则的条件 domain。"""
        self.ensure_one()
        if not self.condition_domain:
            return Domain.TRUE
        try:
            return Domain(safe_eval(self.condition_domain))
        except Exception:  # noqa: BLE001 - 保存时已校验，这里只是运行期兜底
            _logger.exception(
                "InfoHub 规则 %s 的条件 domain 求值失败，本轮忽略该规则", self.name
            )
            return Domain.FALSE

    def _match(self, items):
        """返回命中本规则的条目。"""
        self.ensure_one()
        if not items:
            return items

        domain = self._domain()
        if domain.is_false():
            return items.browse()
        if not domain.is_true():
            items = items.filtered_domain(list(domain))
        if not items or not self.keyword_regex:
            return items

        try:
            pattern = re.compile(self.keyword_regex, re.IGNORECASE)
        except re.error:
            _logger.exception(
                "InfoHub 规则 %s 的正则编译失败，本轮忽略该规则", self.name
            )
            return items.browse()

        return items.filtered(lambda item: self._regex_hit(pattern, item))

    def _regex_hit(self, pattern, item):
        """对单个条目做正则匹配。正文截断到 REGEX_TEXT_LIMIT，见模块文档。"""
        self.ensure_one()
        haystacks = []
        if self.regex_target in ("title", "both"):
            haystacks.append(item.title or "")
        if self.regex_target in ("content", "both"):
            haystacks.append((item.content_text or "")[:REGEX_TEXT_LIMIT])
        return any(pattern.search(text) for text in haystacks if text)

    def _execute(self, items):
        """对命中的条目执行动作。"""
        self.ensure_one()
        if not items:
            return items

        if self.action == "tag":
            items.write({"tag_ids": [(4, tag.id) for tag in self.tag_ids]})
        elif self.action == "score":
            for item in items:
                item.score = (item.score or 0.0) + self.score_delta
        elif self.action == "topic":
            items.write({"topic_ids": [(4, topic.id) for topic in self.topic_ids]})
            if self.set_primary_topic:
                primary = self.topic_ids[0]
                items.filtered(lambda item: not item.primary_topic_id).write(
                    {"primary_topic_id": primary.id}
                )
        elif self.action == "publish":
            items.write({"state": "published", "moderation_note": self._note()})
        elif self.action == "reject":
            items.write({"state": "rejected", "moderation_note": self._note()})

        self.hit_count += len(items)
        return items

    def _note(self):
        self.ensure_one()
        return _("由规则「%s」自动处理。", self.name)

    # ==================================================================
    # 入口
    # ==================================================================
    @api.model
    def _apply(self, items):
        """对条目求值全部规则。

        :return: **未被规则终结**的条目，交回核心走默认审核。这是与核心解耦的
            关键：本模块只负责"哪些条目已经定了状态"，剩下的核心自己决定
            （ADR-009 / R6.4）。
        """
        if not items:
            return items

        eligible = items       # 还要继续过后续规则的
        decided = items.browse()  # 已被终结型动作定下状态的

        for rule in self.search([]):
            if not eligible:
                break
            matched = rule._match(eligible)
            if not matched:
                continue
            rule._execute(matched)

            if rule.action in ("publish", "reject"):
                decided |= matched
                eligible -= matched
            elif rule.stop_after:
                # 不再过后续规则，但状态仍交回核心决定
                eligible -= matched

        return items - decided

    # ==================================================================
    # 试运行
    # ==================================================================
    def action_dry_run(self):
        """在最近的条目样本上试跑本规则，报告命中数。

        写规则时用来确认条件是否如预期，避免直接上线后误伤大批内容。
        只取样本而不全量扫，因为正则匹配是在 Python 里做的，全量会很慢。
        """
        self.ensure_one()
        sample = self.env["infohub.item"].search(
            [], limit=DRY_RUN_SAMPLE, order="published_at desc, id desc"
        )
        matched = self._match(sample)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "info" if matched else "warning",
                "title": _("试运行结果"),
                "message": _(
                    "在最近 %(total)s 条条目中命中 %(hit)s 条。",
                    total=len(sample),
                    hit=len(matched),
                ),
                "sticky": False,
            },
        }

    def action_view_matches(self):
        """打开本规则在样本中命中的条目列表。"""
        self.ensure_one()
        sample = self.env["infohub.item"].search(
            [], limit=DRY_RUN_SAMPLE, order="published_at desc, id desc"
        )
        matched = self._match(sample)
        return {
            "type": "ir.actions.act_window",
            "name": _("「%s」命中的条目", self.name),
            "res_model": "infohub.item",
            "view_mode": "list,form",
            "domain": [("id", "in", matched.ids)],
        }

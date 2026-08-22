# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

import logging

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class CloudAccount(models.Model):
    _name = "one.cloud.account"
    _inherit = ["collection.base"]
    _description = "云账号"
    _rec_name = "name"

    name = fields.Char(required=True)
    provider = fields.Selection(
        selection=[],
        string="云服务商",
        required=True,
        help="由具体的云服务商模块（如 cloud_tencent、cloud_digitalocean）提供可选项",
    )
    active = fields.Boolean(default=True)
    region_ids = fields.Char(
        string="地域",
        help="逗号分隔的地域代码，如 ap-shanghai,ap-tokyo。拉取资源时按这些地域逐一查询；"
             "留空则使用已有目标的地域和连接测试地域",
    )
    target_count = fields.Integer(compute="_compute_target_count", string="资源数量")

    def _compute_target_count(self):
        if "one.cloud.firewall.target" not in self.env:
            for account in self:
                account.target_count = 0
            return
        groups = self.env["one.cloud.firewall.target"]._read_group(
            [("account_id", "in", self.ids)],
            groupby=["account_id"],
            aggregates=["id:count_distinct"],
        )
        counts = {account.id: count for account, count in groups}
        for account in self:
            account.target_count = counts.get(account.id, 0)

    def _get_adapter(self):
        """按 provider 取对应云服务商组件（storage_backend._get_adapter 模式）。"""
        self.ensure_one()
        with self.work_on(self._name) as work:
            return work.component(usage=self.provider)

    def action_test_connection(self):
        """测试连接：调用 adapter 的 validate_config（可选协议，未实现则提示）。"""
        self.ensure_one()
        if not self.provider:
            raise UserError(_("请先选择云服务商"))
        adapter = self._get_adapter()
        if not hasattr(adapter, "validate_config"):
            raise UserError(_("当前云服务商模块未实现连接测试"))
        adapter.validate_config()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("连接测试"),
                "message": _("凭证有效，API 连通正常"),
                "type": "success",
            },
        }

    def action_fetch_targets(self):
        """拉取账号下的防火墙资源，生成/更新防火墙目标。"""
        self.ensure_one()
        Target = self.env["one.cloud.firewall.target"]
        existing = {t.resource_id: t for t in self.target_ids}
        created, updated = 0, 0
        for item in self._get_adapter().list_firewalls():
            resource_id = item["resource_id"]
            values = {
                "name": item["name"],
                "region": item.get("region") or False,
            }
            if resource_id in existing:
                target = existing[resource_id]
                if target.name != values["name"] or target.region != values["region"]:
                    target.write(values)
                    updated += 1
            else:
                Target.create(
                    {"account_id": self.id, "resource_id": resource_id, **values}
                )
                created += 1
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("拉取防火墙目标"),
                "message": _("新增 %(created)s 个，更新 %(updated)s 个", created=created, updated=updated),
                "type": "success",
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

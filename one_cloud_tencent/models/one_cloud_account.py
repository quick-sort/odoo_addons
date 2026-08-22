# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

from odoo import fields, models


class CloudAccount(models.Model):
    _inherit = "one.cloud.account"

    provider = fields.Selection(
        selection_add=[("tencent", "腾讯云轻量应用服务器")],
        ondelete={"tencent": lambda accounts: accounts.unlink()},
    )
    tencent_secret_id = fields.Char(
        string="腾讯云 SecretId",
        groups="one_cloud.group_one_cloud_manager",
    )
    tencent_secret_key = fields.Char(
        string="腾讯云 SecretKey",
        groups="one_cloud.group_one_cloud_manager",
    )
    tencent_test_region = fields.Char(
        string="测试地域",
        default="ap-guangzhou",
        help="连接测试用的地域（Lighthouse API 按地域调用）",
        groups="one_cloud.group_one_cloud_manager",
    )

    _provider_tencent_creds = models.Constraint(
        "CHECK(provider <> 'tencent' OR "
        "(tencent_secret_id IS NOT NULL AND tencent_secret_id <> '' "
        "AND tencent_secret_key IS NOT NULL AND tencent_secret_key <> ''))",
        "腾讯云账号必须填写 SecretId 和 SecretKey",
    )

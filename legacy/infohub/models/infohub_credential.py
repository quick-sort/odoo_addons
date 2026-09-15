"""信息源凭证。

单独建模而不是在 ``infohub.source`` 上放字段，目的是把访问控制收窄到一个模型：
凭证只对 ``infohub.group_manager`` 可读，而信息源本身对 portal 读者可读
（他们要按源订阅）。如果把 token 放在源记录上，任何能读源的人都能读到它。

见 requirements.md N6、R1.7。
"""

from odoo import api, fields, models


class InfohubCredential(models.Model):
    _name = "infohub.credential"
    _description = "InfoHub 凭证"
    _order = "name"

    name = fields.Char(string="名称", required=True)
    auth_type = fields.Selection(
        [
            ("none", "无"),
            ("api_key", "API Key"),
            ("bearer", "Bearer Token"),
            ("basic", "HTTP Basic"),
        ],
        string="认证方式",
        required=True,
        default="api_key",
    )
    #: 各卫星模块可按需扩展认证方式与字段
    api_key = fields.Char(string="API Key")
    username = fields.Char(string="用户名")
    password = fields.Char(string="密码")
    header_name = fields.Char(
        string="请求头名称",
        default="Authorization",
        help="api_key 方式下，凭证放在哪个请求头里。",
    )
    note = fields.Text(string="备注")
    source_ids = fields.One2many("infohub.source", "credential_id", string="使用的源")
    source_count = fields.Integer(string="源数量", compute="_compute_source_count")

    @api.depends("source_ids")
    def _compute_source_count(self):
        for credential in self:
            credential.source_count = len(credential.source_ids)

    def auth_headers(self):
        """返回该凭证对应的请求头。

        供传输 component 使用::

            headers = source.credential_id.auth_headers()
        """
        if not self:
            return {}
        self.ensure_one()
        if self.auth_type == "api_key" and self.api_key:
            return {self.header_name or "Authorization": self.api_key}
        if self.auth_type == "bearer" and self.api_key:
            return {"Authorization": f"Bearer {self.api_key}"}
        return {}

    def basic_auth(self):
        """返回 requests 的 ``auth`` 参数，非 basic 方式返回 None。"""
        if not self:
            return None
        self.ensure_one()
        if self.auth_type == "basic" and self.username:
            return (self.username, self.password or "")
        return None

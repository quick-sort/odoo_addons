import base64
import hashlib
import hmac

from odoo import _, fields, models
from odoo.exceptions import AccessError


class AgenthubAgent(models.Model):
    _inherit = "agenthub.agent"

    provisioner_token_version = fields.Integer(
        default=1,
        copy=False,
        groups="base.group_system",
        help="Bump to rotate the relay token derived for this agent.",
    )
    deployment_ids = fields.One2many(
        "agenthub.agent.deployment",
        "agent_id",
        string="Deployments",
        groups="base.group_system",
    )
    deployment_count = fields.Integer(
        compute="_compute_deployment_count",
        groups="base.group_system",
    )

    def _compute_deployment_count(self):
        for agent in self:
            agent.deployment_count = len(agent.deployment_ids)

    def _provisioner_token(self):
        """Derive the relay token without storing its plaintext."""
        self.ensure_one()
        secret = self.env["agenthub.agent.deployment"]._token_secret()
        message = "agenthub.agent:%s:%s" % (
            self.id,
            self.provisioner_token_version or 1,
        )
        digest = hmac.new(
            secret.encode(), message.encode(), hashlib.sha256
        ).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()

    def action_open_deployments(self):
        self.ensure_one()
        if not self.env.user.has_group("base.group_system"):
            raise AccessError(
                _("Only system administrators can manage agent deployments.")
            )
        return {
            "type": "ir.actions.act_window",
            "name": _("Deployments"),
            "res_model": "agenthub.agent.deployment",
            "view_mode": "list,form",
            "domain": [("agent_id", "=", self.id)],
            "context": {"default_agent_id": self.id},
        }

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from ..utils import validate_env


class AgenthubProvisionerLlm(models.Model):
    _name = "agenthub.provisioner.llm"
    _description = "Agent Hub Provisioner LLM Profile"
    _order = "name"

    name = fields.Char(required=True)
    base_url = fields.Char(help="LLM gateway base URL; rendered as ANTHROPIC_BASE_URL.")
    auth_mode = fields.Selection(
        [("api_key", "API Key"), ("auth_token", "Auth Token")],
        default="api_key",
        required=True,
    )
    secret = fields.Char(
        groups="base.group_system",
        help="API key or auth token injected into the agent-box container.",
    )
    router_model = fields.Char(help="Rendered as ANTHROPIC_SMALL_FAST_MODEL.")
    haiku_model = fields.Char(help="Rendered as ANTHROPIC_DEFAULT_HAIKU_MODEL.")
    sonnet_model = fields.Char(help="Rendered as ANTHROPIC_DEFAULT_SONNET_MODEL.")
    opus_model = fields.Char(help="Rendered as ANTHROPIC_DEFAULT_OPUS_MODEL.")
    extra_env = fields.Json()
    active = fields.Boolean(default=True)

    _llm_name_uniq = models.Constraint(
        "UNIQUE(name)",
        "LLM profile names must be unique.",
    )

    @api.constrains("router_model", "haiku_model")
    def _check_router_model(self):
        for profile in self:
            if not profile.router_model and not profile.haiku_model:
                raise ValidationError(
                    _(
                        "LLM profile '%s' needs a router model or a Haiku model; "
                        "agent-box cannot start without one."
                    )
                    % profile.name
                )

    def _render_env(self):
        self.ensure_one()
        env = {}
        if self.base_url:
            env["ANTHROPIC_BASE_URL"] = self.base_url
        if self.secret:
            if self.auth_mode == "auth_token":
                env["ANTHROPIC_AUTH_TOKEN"] = self.secret
            else:
                env["ANTHROPIC_API_KEY"] = self.secret
        if self.router_model:
            env["ANTHROPIC_SMALL_FAST_MODEL"] = self.router_model
        if self.haiku_model:
            env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = self.haiku_model
        if self.sonnet_model:
            env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = self.sonnet_model
        if self.opus_model:
            env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = self.opus_model
        env.update(validate_env(self.extra_env or {}))
        return env

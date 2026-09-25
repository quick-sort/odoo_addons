from odoo import fields, models, _
from odoo.exceptions import UserError

_DEFAULT_SCOPE = "offline_access openid profile Files.Read.All Sites.Read.All"


class MicrosoftGraphApplication(models.Model):
    _name = "microsoft.graph.application"
    _inherit = "server.env.mixin"
    _description = "Microsoft Graph Application"
    _order = "name"

    name = fields.Char(required=True)
    graph_tenant_id = fields.Char(
        string="Entra Tenant ID",
        help="Tenant GUID or verified tenant domain used by the OAuth v2 endpoints.",
    )
    graph_client_id = fields.Char(string="Entra Application (Client) ID")
    graph_client_secret = fields.Char(
        string="Entra Client Secret",
        groups="base.group_system",
        help="Prefer providing this value through server_environment.",
    )
    graph_scope = fields.Char(
        string="Delegated OAuth Scopes",
        default=_DEFAULT_SCOPE,
        help=(
            "Space-separated delegated scopes shared by every consumer of this "
            "application. The defaults are read-only; grant the corresponding "
            "ReadWrite scopes only when some consumer needs to write."
        ),
    )
    allow_user_authorization = fields.Boolean(
        string="Allow User Authorization",
        default=True,
        help=(
            "Allow signed-in Odoo users to start delegated OAuth for this "
            "application. Microsoft applies each user's native permissions."
        ),
    )
    credential_ids = fields.One2many(
        "microsoft.graph.credential",
        "application_id",
        string="User Credentials",
    )
    graph_current_user_authorized = fields.Boolean(
        string="Current User Authorized",
        compute="_compute_graph_current_user_authorized",
    )

    @property
    def _server_env_fields(self):
        return {
            "graph_tenant_id": {},
            "graph_client_id": {},
            "graph_client_secret": {},
            "graph_scope": {},
            "allow_user_authorization": {},
        }

    def _compute_graph_current_user_authorized(self):
        Credential = self.env["microsoft.graph.credential"].sudo()
        for application in self:
            application.graph_current_user_authorized = bool(
                Credential.search_count(
                    [
                        ("application_id", "=", application.id),
                        ("user_id", "=", self.env.user.id),
                        "|",
                        ("access_token", "!=", False),
                        ("refresh_token", "!=", False),
                    ],
                    limit=1,
                )
            )

    def _graph_validate_configuration(self):
        self.ensure_one()
        application = self.sudo()
        missing = [
            label
            for value, label in (
                (application.graph_tenant_id, _("Entra Tenant ID")),
                (application.graph_client_id, _("Entra Application ID")),
            )
            if not value
        ]
        if missing:
            raise UserError(
                _("Missing Microsoft Graph configuration: %s", ", ".join(missing))
            )
        return True

    def action_graph_authorize(self):
        self.ensure_one()
        return self.env["microsoft.graph.service"]._authorization_action(self)

    def action_graph_disconnect(self):
        self.ensure_one()
        self.env["microsoft.graph.service"]._disconnect(self, self.env.user)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Microsoft account disconnected"),
                "message": _("Your delegated Microsoft Graph credential was removed."),
                "type": "success",
                "sticky": False,
            },
        }

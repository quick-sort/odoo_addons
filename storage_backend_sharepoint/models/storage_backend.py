from odoo import fields, models, _
from odoo.exceptions import UserError


class StorageBackend(models.Model):
    _inherit = "storage.backend"

    backend_type = fields.Selection(
        selection_add=[("sharepoint", "Microsoft SharePoint")],
        ondelete={"sharepoint": "set default"},
    )
    sharepoint_tenant_id = fields.Char(
        string="Entra Tenant ID",
        help="Tenant GUID or verified tenant domain used by the OAuth v2 endpoints.",
    )
    sharepoint_client_id = fields.Char(string="Entra Application (Client) ID")
    sharepoint_client_secret = fields.Char(
        string="Entra Client Secret",
        groups="base.group_system",
        help="Prefer providing this value through server_environment.",
    )
    sharepoint_scope = fields.Char(
        string="Delegated OAuth Scopes",
        default="offline_access openid profile Files.Read.All Sites.Read.All",
        help=(
            "Space-separated delegated scopes. The defaults are read-only. "
            "Use the corresponding ReadWrite scopes only when this backend is writable."
        ),
    )
    sharepoint_site_id = fields.Char(
        string="SharePoint Site ID",
        help="Optional informational Graph site ID for this document library.",
    )
    sharepoint_drive_id = fields.Char(
        string="Document Library (Drive) ID",
        help="Stable Microsoft Graph drive ID of the SharePoint document library.",
    )
    sharepoint_root_item_id = fields.Char(
        string="Root Item ID",
        help=(
            "Optional stable driveItem ID used as this backend's root. When empty, "
            "the document library root is used. directory_path is applied below it."
        ),
    )
    sharepoint_read_only = fields.Boolean(
        string="Read Only",
        default=True,
        help="Block uploads, renames, moves and deletions in Odoo.",
    )
    sharepoint_allow_user_authorization = fields.Boolean(
        string="Allow User Authorization",
        default=True,
        help=(
            "Allow signed-in Odoo users to start delegated OAuth for this backend. "
            "SharePoint still enforces each user's native permissions."
        ),
    )
    sharepoint_current_user_authorized = fields.Boolean(
        string="Current User Authorized",
        compute="_compute_sharepoint_current_user_authorized",
    )

    @property
    def _server_env_fields(self):
        env_fields = super()._server_env_fields
        env_fields.update(
            {
                "sharepoint_tenant_id": {},
                "sharepoint_client_id": {},
                "sharepoint_client_secret": {},
                "sharepoint_scope": {},
                "sharepoint_site_id": {},
                "sharepoint_drive_id": {},
                "sharepoint_root_item_id": {},
                "sharepoint_read_only": {},
                "sharepoint_allow_user_authorization": {},
            }
        )
        return env_fields

    def _compute_sharepoint_current_user_authorized(self):
        Credential = self.env["storage.sharepoint.credential"].sudo()
        for backend in self:
            backend.sharepoint_current_user_authorized = bool(
                backend.backend_type == "sharepoint"
                and Credential.search_count(
                    [
                        ("backend_id", "=", backend.id),
                        ("user_id", "=", self.env.user.id),
                        "|",
                        ("access_token", "!=", False),
                        ("refresh_token", "!=", False),
                    ],
                    limit=1,
                )
            )

    def _sharepoint_validate_configuration(self):
        self.ensure_one()
        backend = self.sudo()
        if backend.backend_type != "sharepoint":
            raise UserError(_("This storage backend is not a SharePoint backend."))
        missing = [
            label
            for value, label in (
                (backend.sharepoint_tenant_id, _("Entra Tenant ID")),
                (backend.sharepoint_client_id, _("Entra Application ID")),
                (backend.sharepoint_drive_id, _("Document Library Drive ID")),
            )
            if not value
        ]
        if missing:
            raise UserError(
                _("Missing SharePoint configuration: %s", ", ".join(missing))
            )
        return True

    def action_sharepoint_authorize(self):
        self.ensure_one()
        self._sharepoint_validate_configuration()
        return self.env["sharepoint.graph.service"]._authorization_action(self)

    def action_sharepoint_disconnect(self):
        self.ensure_one()
        self.env["sharepoint.graph.service"]._disconnect(self, self.env.user)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("SharePoint disconnected"),
                "message": _("Your delegated SharePoint credential was removed."),
                "type": "success",
                "sticky": False,
            },
        }

from odoo import fields, models, _
from odoo.exceptions import UserError


class StorageBackend(models.Model):
    _inherit = "storage.backend"

    backend_type = fields.Selection(
        selection_add=[("sharepoint", "Microsoft SharePoint")],
        ondelete={"sharepoint": "set default"},
    )
    sharepoint_application_id = fields.Many2one(
        "microsoft.graph.application",
        string="Microsoft Graph Application",
        ondelete="restrict",
        help=(
            "Entra application registration providing delegated OAuth for this "
            "backend. Its configured scopes must include the SharePoint drive "
            "permissions this backend needs."
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
    sharepoint_current_user_authorized = fields.Boolean(
        string="Current User Authorized",
        compute="_compute_sharepoint_current_user_authorized",
    )

    @property
    def _server_env_fields(self):
        env_fields = super()._server_env_fields
        env_fields.update(
            {
                "sharepoint_site_id": {},
                "sharepoint_drive_id": {},
                "sharepoint_root_item_id": {},
                "sharepoint_read_only": {},
            }
        )
        return env_fields

    def _sharepoint_application(self):
        self.ensure_one()
        application = self.sudo().sharepoint_application_id
        if not application:
            raise UserError(
                _("Missing SharePoint configuration: %s", _("Microsoft Graph Application"))
            )
        return application

    def _compute_sharepoint_current_user_authorized(self):
        Credential = self.env["microsoft.graph.credential"].sudo()
        for backend in self:
            backend.sharepoint_current_user_authorized = bool(
                backend.backend_type == "sharepoint"
                and backend.sharepoint_application_id
                and Credential.search_count(
                    [
                        (
                            "application_id",
                            "=",
                            backend.sharepoint_application_id.id,
                        ),
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
                (
                    backend.sharepoint_application_id,
                    _("Microsoft Graph Application"),
                ),
                (backend.sharepoint_drive_id, _("Document Library Drive ID")),
            )
            if not value
        ]
        if missing:
            raise UserError(
                _("Missing SharePoint configuration: %s", ", ".join(missing))
            )
        backend.sharepoint_application_id._graph_validate_configuration()
        return True

    def action_sharepoint_authorize(self):
        self.ensure_one()
        self._sharepoint_validate_configuration()
        return self.env["microsoft.graph.service"]._authorization_action(
            self.sudo().sharepoint_application_id,
            redirect_to=f"/web#id={self.id}&model=storage.backend&view_type=form",
        )

    def action_sharepoint_disconnect(self):
        self.ensure_one()
        self.env["microsoft.graph.service"]._disconnect(
            self._sharepoint_application(), self.env.user
        )
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

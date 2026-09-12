from odoo import fields, models


class SharePointCredential(models.Model):
    _name = "storage.sharepoint.credential"
    _description = "Per-user SharePoint Delegated Credential"
    _order = "backend_id, user_id"

    backend_id = fields.Many2one(
        "storage.backend", required=True, index=True, ondelete="cascade"
    )
    user_id = fields.Many2one(
        "res.users", required=True, index=True, ondelete="cascade"
    )
    entra_oid = fields.Char(string="Entra Object ID", readonly=True, index=True)
    access_token = fields.Char(
        copy=False, prefetch=False, groups=fields.NO_ACCESS
    )
    refresh_token = fields.Char(
        copy=False, prefetch=False, groups=fields.NO_ACCESS
    )
    token_expiry = fields.Datetime(copy=False, groups="base.group_system")
    granted_scope = fields.Char(copy=False, groups="base.group_system")
    oauth_state = fields.Char(
        copy=False, index=True, prefetch=False, groups=fields.NO_ACCESS
    )
    oauth_state_expiry = fields.Datetime(copy=False, groups=fields.NO_ACCESS)
    oauth_code_verifier = fields.Char(
        copy=False, prefetch=False, groups=fields.NO_ACCESS
    )

    _backend_user_unique = models.Constraint(
        "unique(backend_id, user_id)",
        "A user can only have one delegated credential per SharePoint backend.",
    )

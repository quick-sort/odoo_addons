from odoo import fields, models


class MicrosoftGraphCredential(models.Model):
    _name = "microsoft.graph.credential"
    _description = "Per-user Microsoft Graph Delegated Credential"
    _order = "application_id, user_id"

    application_id = fields.Many2one(
        "microsoft.graph.application",
        required=True,
        index=True,
        ondelete="cascade",
    )
    user_id = fields.Many2one(
        "res.users", required=True, index=True, ondelete="cascade"
    )
    entra_oid = fields.Char(string="Entra Object ID", readonly=True, index=True)
    access_token = fields.Char(copy=False, prefetch=False, groups=fields.NO_ACCESS)
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
    post_auth_redirect = fields.Char(copy=False, prefetch=False, groups=fields.NO_ACCESS)

    _application_user_unique = models.Constraint(
        "unique(application_id, user_id)",
        "A user can only have one delegated credential per application.",
    )

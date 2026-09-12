from odoo import models, _
from odoo.exceptions import AccessError


class ResUsers(models.Model):
    _inherit = "res.users"

    def _set_sharepoint_auth_tokens(
        self,
        backend,
        access_token,
        refresh_token=None,
        expires_in=None,
        scope=None,
        entra_oid=None,
    ):
        """Hook for an Entra SSO addon to persist delegated Graph tokens.

        The SSO addon should call this after an authorization-code exchange. Tokens
        must be issued for Microsoft Graph and for the same Entra user as ``self``.
        """
        self.ensure_one()
        if self != self.env.user and not self.env.user.has_group("base.group_system"):
            raise AccessError(_("You can only bind your own SharePoint credential."))
        token_data = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": expires_in,
            "scope": scope,
        }
        return self.env["sharepoint.graph.service"]._store_user_tokens(
            backend, self, token_data, entra_oid=entra_oid
        )

    def _get_sharepoint_access_token(self, backend):
        self.ensure_one()
        if self != self.env.user and not self.env.user.has_group("base.group_system"):
            raise AccessError(_("You can only use your own SharePoint credential."))
        return self.env["sharepoint.graph.service"]._get_access_token(backend, self)

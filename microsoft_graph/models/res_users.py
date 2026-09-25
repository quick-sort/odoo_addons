from odoo import models, _
from odoo.exceptions import AccessError


class ResUsers(models.Model):
    _inherit = "res.users"

    def _set_microsoft_graph_tokens(
        self,
        application,
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
            raise AccessError(_("You can only bind your own Microsoft credential."))
        token_data = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": expires_in,
            "scope": scope,
        }
        return self.env["microsoft.graph.service"]._store_user_tokens(
            application, self, token_data, entra_oid=entra_oid
        )

    def _get_microsoft_graph_access_token(self, application):
        self.ensure_one()
        if self != self.env.user and not self.env.user.has_group("base.group_system"):
            raise AccessError(_("You can only use your own Microsoft credential."))
        return self.env["microsoft.graph.service"]._get_access_token(
            application, self
        )

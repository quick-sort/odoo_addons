"""One-time display wizard for a direct Qdrant JWT."""

import hashlib

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class QdrantCredentialIssueWizard(models.TransientModel):
    _name = "llm.qdrant.credential.issue.wizard"
    _description = "Issue Qdrant Credential"

    principal_id = fields.Many2one(
        "llm.qdrant.principal", required=True, readonly=True
    )
    store_id = fields.Many2one(related="principal_id.store_id", readonly=True)
    expires_in = fields.Integer(
        string="Lifetime (seconds)", required=True, default=86400
    )
    state = fields.Selection(
        [("confirm", "Confirm"), ("done", "Done")],
        required=True,
        default="confirm",
    )
    credential_id = fields.Many2one(
        "llm.qdrant.credential", string="Credential Record", readonly=True
    )
    endpoint = fields.Char(readonly=True)
    secret = fields.Text(string="Token", compute="_compute_secret", readonly=True)
    access_snapshot = fields.Json(readonly=True)

    @api.depends_context("qdrant_issued_secret")
    def _compute_secret(self):
        secret = self.env.context.get("qdrant_issued_secret", False)
        for wizard in self:
            wizard.secret = secret

    @api.onchange("principal_id")
    def _onchange_principal_id(self):
        if self.principal_id:
            self.expires_in = self.principal_id.store_id.qdrant_default_token_ttl

    def action_issue(self):
        self.ensure_one()
        if self.state == "done":
            raise UserError(_("This wizard has already issued a credential."))
        principal = self.principal_id
        result = principal.store_id.issue_qdrant_credential(
            principal,
            principal.grant_ids.filtered("active"),
            expires_in=self.expires_in,
        )
        secret = result.pop("secret")
        credential = self.env["llm.qdrant.credential"].create(
            {
                "name": _(
                    "%(principal)s credential %(prefix)s",
                    principal=principal.name,
                    prefix=secret[:12],
                ),
                "principal_id": principal.id,
                "store_id": principal.store_id.id,
                "provider_credential_id": result.pop("provider_credential_id"),
                "secret_prefix": secret[:12],
                "secret_fingerprint": hashlib.sha256(
                    secret.encode("utf-8")
                ).hexdigest(),
                "token_version": principal.token_version,
                "issued_at": result.pop("issued_at"),
                "expires_at": result.pop("expires_at", False),
                "access_snapshot": result.pop("access_snapshot", []),
                "provider_metadata": result.pop("provider_metadata", {}),
            }
        )
        self.write(
            {
                "state": "done",
                "credential_id": credential.id,
                "endpoint": principal.store_id.connection_uri,
                "access_snapshot": credential.access_snapshot,
            }
        )
        return {
            "name": _("Direct Qdrant Credential"),
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
            "context": dict(
                self.env.context,
                qdrant_issued_secret=secret,
            ),
        }

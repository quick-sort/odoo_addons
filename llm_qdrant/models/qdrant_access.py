"""Qdrant-specific direct-client principals, grants, and credentials."""

import uuid as uuid_lib

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class QdrantPrincipal(models.Model):
    _name = "llm.qdrant.principal"
    _inherit = ["mail.thread"]
    _description = "Qdrant Access Principal"
    _order = "store_id, name, id"

    name = fields.Char(required=True, tracking=True)
    store_id = fields.Many2one(
        "llm.store",
        required=True,
        ondelete="cascade",
        index=True,
        tracking=True,
        domain="[('service', '=', 'qdrant')]",
    )
    uuid = fields.Char(
        required=True,
        default=lambda self: str(uuid_lib.uuid4()),
        copy=False,
        readonly=True,
        index=True,
    )
    subject = fields.Char(required=True, copy=False, index=True)
    principal_type = fields.Selection(
        [("service", "Service Account"), ("user", "User")],
        required=True,
        default="service",
        tracking=True,
    )
    active = fields.Boolean(default=True, tracking=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("active", "Active"),
            ("error", "Error"),
            ("revoked", "Revoked"),
        ],
        required=True,
        default="draft",
        copy=False,
        tracking=True,
    )
    token_version = fields.Integer(
        required=True, default=1, copy=False, readonly=True
    )
    metadata = fields.Json()
    last_error = fields.Text(readonly=True, copy=False)
    grant_ids = fields.One2many(
        "llm.qdrant.grant", "principal_id", string="Collection Grants"
    )
    credential_ids = fields.One2many(
        "llm.qdrant.credential", "principal_id", string="Credentials"
    )
    grant_count = fields.Integer(compute="_compute_counts")
    credential_count = fields.Integer(compute="_compute_counts")

    _unique_uuid = models.Constraint(
        "UNIQUE(uuid)", "Qdrant principal UUIDs must be unique."
    )
    _unique_subject_per_store = models.Constraint(
        "UNIQUE(store_id, subject)",
        "Qdrant principal subjects must be unique per store instance.",
    )

    @api.constrains("store_id")
    def _check_qdrant_store(self):
        for principal in self:
            if principal.store_id.service != "qdrant":
                raise ValidationError(
                    _("Qdrant principals require a Qdrant store instance.")
                )

    @api.depends("grant_ids", "credential_ids")
    def _compute_counts(self):
        for principal in self:
            principal.grant_count = len(principal.grant_ids)
            principal.credential_count = len(principal.credential_ids)

    @api.model_create_multi
    def create(self, vals_list):
        normalized = []
        for values in vals_list:
            values = dict(values)
            values["subject"] = (values.get("subject") or "").strip()
            normalized.append(values)
        principals = super().create(normalized)
        principals.write({"state": "active"})
        return principals

    def write(self, vals):
        if "store_id" in vals and any(
            principal.store_id.id != vals.get("store_id") for principal in self
        ):
            raise UserError(_("A Qdrant principal cannot move between stores."))
        if "uuid" in vals:
            raise UserError(_("The Qdrant principal UUID is immutable."))
        if "subject" in vals:
            normalized = (vals.get("subject") or "").strip()
            if any(principal.subject != normalized for principal in self):
                raise UserError(_("The Qdrant principal subject is immutable."))
        if "token_version" in vals and not self.env.context.get(
            "allow_token_version_write"
        ):
            raise UserError(_("Token version is managed by credential lifecycle."))
        if vals.get("active") is False or vals.get("state") == "revoked":
            self._revoke_active_credentials()
            vals = dict(vals, state="revoked", active=False)
        return super().write(vals)

    def _revoke_active_credentials(self):
        for principal in self:
            active_credentials = principal.credential_ids.filtered(
                lambda credential: credential.state == "active"
            )
            for credential in active_credentials:
                credential.action_revoke()
            if active_credentials:
                principal.with_context(allow_token_version_write=True).write(
                    {"token_version": principal.token_version + 1}
                )
        return True

    def action_issue_credential(self):
        self.ensure_one()
        if not self.active or self.state != "active":
            raise UserError(_("Only active principals can receive credentials."))
        if not self.grant_ids.filtered("active"):
            raise UserError(_("Assign at least one active collection grant first."))
        return {
            "name": _("Issue Qdrant Credential"),
            "type": "ir.actions.act_window",
            "res_model": "llm.qdrant.credential.issue.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_principal_id": self.id},
        }

    def action_view_credentials(self):
        self.ensure_one()
        return {
            "name": _("Qdrant Credentials"),
            "type": "ir.actions.act_window",
            "res_model": "llm.qdrant.credential",
            "view_mode": "list,form",
            "domain": [("principal_id", "=", self.id)],
        }

    def action_revoke_all_credentials(self):
        self._revoke_active_credentials()
        return True

    def unlink(self):
        self._revoke_active_credentials()
        return super().unlink()


class QdrantGrant(models.Model):
    _name = "llm.qdrant.grant"
    _description = "Qdrant Principal Collection Grant"
    _order = "principal_id, database_id, id"

    principal_id = fields.Many2one(
        "llm.qdrant.principal", required=True, ondelete="cascade", index=True
    )
    store_id = fields.Many2one(
        related="principal_id.store_id", store=True, readonly=True, index=True
    )
    database_id = fields.Many2one(
        "llm.store.database",
        required=True,
        ondelete="cascade",
        index=True,
        domain="[('store_id', '=', store_id), ('isolation_mode', '=', 'database')]",
    )
    permission = fields.Selection(
        [("read", "Read"), ("read_write", "Read / Write")],
        required=True,
        default="read",
    )
    active = fields.Boolean(default=True)
    valid_from = fields.Datetime()
    valid_until = fields.Datetime()
    provider_metadata = fields.Json(readonly=True, copy=False)
    last_error = fields.Text(readonly=True, copy=False)

    _unique_principal_database = models.Constraint(
        "UNIQUE(principal_id, database_id)",
        "A Qdrant principal can have only one grant per database.",
    )

    @api.constrains("principal_id", "database_id", "valid_from", "valid_until")
    def _check_scope(self):
        for grant in self:
            if grant.principal_id.store_id != grant.database_id.store_id:
                raise ValidationError(
                    _("The principal and database must use the same Qdrant store.")
                )
            if grant.database_id.store_id.service != "qdrant":
                raise ValidationError(_("The granted database must use Qdrant."))
            if grant.database_id.isolation_mode != "database":
                raise ValidationError(
                    _("Direct Qdrant grants require dedicated resource isolation.")
                )
            if grant.valid_from and grant.valid_until and grant.valid_until <= grant.valid_from:
                raise ValidationError(_("Grant expiration must follow its start time."))

    def write(self, vals):
        security_fields = {
            "principal_id",
            "database_id",
            "permission",
            "active",
            "valid_from",
            "valid_until",
        }
        principals = (
            self.mapped("principal_id")
            if security_fields.intersection(vals)
            else self.env["llm.qdrant.principal"]
        )
        result = super().write(vals)
        principals._revoke_active_credentials()
        return result

    def unlink(self):
        principals = self.mapped("principal_id")
        result = super().unlink()
        principals._revoke_active_credentials()
        return result


class QdrantCredential(models.Model):
    _name = "llm.qdrant.credential"
    _description = "Qdrant Principal Credential"
    _order = "issued_at desc, id desc"

    name = fields.Char(required=True, readonly=True)
    principal_id = fields.Many2one(
        "llm.qdrant.principal", required=True, ondelete="cascade", index=True
    )
    store_id = fields.Many2one(
        "llm.store",
        required=True,
        readonly=True,
        copy=False,
        ondelete="restrict",
        index=True,
    )
    provider_credential_id = fields.Char(readonly=True, copy=False, index=True)
    secret_prefix = fields.Char(readonly=True, copy=False)
    secret_fingerprint = fields.Char(readonly=True, copy=False, index=True)
    token_version = fields.Integer(readonly=True, copy=False)
    issued_at = fields.Datetime(required=True, readonly=True, copy=False)
    expires_at = fields.Datetime(readonly=True, copy=False)
    revoked_at = fields.Datetime(readonly=True, copy=False)
    state = fields.Selection(
        [
            ("active", "Active"),
            ("expired", "Expired"),
            ("revoked", "Revoked"),
            ("error", "Error"),
        ],
        required=True,
        default="active",
        readonly=True,
        copy=False,
    )
    access_snapshot = fields.Json(readonly=True, copy=False)
    provider_metadata = fields.Json(readonly=True, copy=False)
    last_error = fields.Text(readonly=True, copy=False)

    _unique_provider_credential = models.Constraint(
        "UNIQUE(store_id, provider_credential_id)",
        "Qdrant credential IDs must be unique per store instance.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        normalized = []
        Principal = self.env["llm.qdrant.principal"]
        for values in vals_list:
            values = dict(values)
            principal = Principal.browse(values.get("principal_id")).exists()
            if principal:
                values.setdefault("store_id", principal.store_id.id)
            normalized.append(values)
        return super().create(normalized)

    @api.constrains("principal_id", "store_id")
    def _check_issuing_store(self):
        for credential in self:
            if credential.store_id != credential.principal_id.store_id:
                raise ValidationError(
                    _("The credential issuing store must own its principal.")
                )

    def write(self, vals):
        immutable = {"principal_id", "store_id"}.intersection(vals)
        if immutable:
            raise UserError(_("Credential ownership is immutable."))
        return super().write(vals)

    def action_revoke(self):
        for credential in self:
            if credential.state in ("revoked", "expired"):
                continue
            try:
                credential.store_id.revoke_qdrant_credential(credential)
                credential.write(
                    {
                        "state": "revoked",
                        "revoked_at": fields.Datetime.now(),
                        "last_error": False,
                    }
                )
            except Exception as error:
                credential.write({"state": "error", "last_error": str(error)})
                raise
        return True

    def unlink(self):
        active = self.filtered(lambda credential: credential.state == "active")
        active.action_revoke()
        return super().unlink()

import re
import uuid as uuid_lib

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.llm.models.llm_service_dispatch import archive_dangling_service


class LLMStore(models.Model):
    _inherit = "llm.store"

    service = fields.Selection(
        selection_add=[("qdrant", "Qdrant")],
        ondelete={"qdrant": archive_dangling_service},
    )
    qdrant_instance_uuid = fields.Char(
        string="Qdrant Instance UUID",
        required=True,
        default=lambda self: str(uuid_lib.uuid4()),
        copy=False,
        readonly=True,
        index=True,
        groups="llm.group_llm_manager",
    )
    qdrant_jwt_rbac = fields.Boolean(
        string="JWT RBAC Enabled",
        groups="llm.group_llm_manager",
        help="The server must have service.jwt_rbac enabled. The administrator "
        "secret signs collection-scoped HS256 tokens.",
    )
    qdrant_auth_collection = fields.Char(
        string="Credential Registry Collection",
        copy=False,
        groups="llm.group_llm_manager",
        help="Reserved Qdrant collection used for immediate token revocation.",
    )
    qdrant_default_token_ttl = fields.Integer(
        string="Default Token Lifetime (seconds)",
        default=86400,
        groups="llm.group_llm_manager",
    )
    qdrant_principal_ids = fields.One2many(
        "llm.qdrant.principal",
        "store_id",
        string="Qdrant Principals",
        groups="llm.group_llm_manager",
    )
    qdrant_principal_count = fields.Integer(
        compute="_compute_qdrant_principal_count",
        groups="llm.group_llm_manager",
    )

    _unique_qdrant_instance_uuid = models.Constraint(
        "UNIQUE(qdrant_instance_uuid)",
        "Qdrant instance UUIDs must be unique.",
    )

    @api.depends("qdrant_principal_ids")
    def _compute_qdrant_principal_count(self):
        for store in self:
            store.qdrant_principal_count = len(store.qdrant_principal_ids)

    @staticmethod
    def _qdrant_sanitize_name(name):
        value = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(name or "").strip())
        value = re.sub(r"[-_.]{2,}", "-", value).strip("-_.")
        return value[:200] or "odoo-vectors"

    def _qdrant_registry_name(self):
        self.ensure_one()
        base_name = self._qdrant_sanitize_name(
            self.qdrant_auth_collection
            or f"odoo-{self.env.cr.dbname}-credential-registry"
        )
        suffix = f"-{self.qdrant_instance_uuid}"
        max_base_length = 200 - len(suffix)
        base_name = base_name[:max_base_length].rstrip("-_.") or "odoo"
        return f"{base_name}{suffix}"

    @api.model_create_multi
    def create(self, vals_list):
        normalized = []
        for values in vals_list:
            values = dict(values)
            if values.get("qdrant_auth_collection"):
                values["qdrant_auth_collection"] = self._qdrant_sanitize_name(
                    values["qdrant_auth_collection"]
                )
            normalized.append(values)
        return super().create(normalized)

    def write(self, vals):
        if "service" in vals:
            leaving_qdrant = self.filtered(
                lambda store: store.service == "qdrant"
                and vals.get("service") != "qdrant"
                and store.qdrant_principal_ids
            )
            if leaving_qdrant:
                raise ValidationError(
                    _(
                        "Remove all Qdrant principals and revoke their credentials "
                        "before changing the store service."
                    )
                )
        if "qdrant_instance_uuid" in vals and any(
            store.qdrant_instance_uuid != vals.get("qdrant_instance_uuid")
            for store in self
        ):
            raise UserError(_("The Qdrant instance UUID is immutable."))
        if vals.get("qdrant_auth_collection"):
            vals = dict(vals)
            vals["qdrant_auth_collection"] = self._qdrant_sanitize_name(
                vals["qdrant_auth_collection"]
            )
        return super().write(vals)

    @api.constrains("service", "qdrant_auth_collection")
    def _check_qdrant_registry_name(self):
        Database = self.env["llm.store.database"]
        for store in self.filtered(lambda item: item.service == "qdrant"):
            registry = store._qdrant_registry_name()
            if Database.search_count(
                [
                    ("store_id", "=", store.id),
                    ("database_name", "=", registry),
                ]
            ):
                raise ValidationError(
                    _(
                        "Qdrant credential registry '%s' conflicts with a managed "
                        "database collection.",
                        registry,
                    )
                )

    @api.constrains("qdrant_default_token_ttl")
    def _check_qdrant_token_ttl(self):
        for store in self.filtered(lambda item: item.service == "qdrant"):
            if store.qdrant_default_token_ttl <= 0:
                raise ValidationError(_("Qdrant token lifetime must be positive."))

    @api.ondelete(at_uninstall=False)
    def _unlink_except_qdrant_principals(self):
        for store in self:
            if store.qdrant_principal_ids:
                raise ValidationError(
                    _(
                        "Qdrant store '%s' still owns access principals. Remove "
                        "them before deleting the instance.",
                        store.name,
                    )
                )

    def action_view_qdrant_principals(self):
        self.ensure_one()
        return {
            "name": _("Qdrant Principals"),
            "type": "ir.actions.act_window",
            "res_model": "llm.qdrant.principal",
            "view_mode": "list,form",
            "domain": [("store_id", "=", self.id)],
            "context": {"default_store_id": self.id},
        }

    def qdrant_access_capabilities(self):
        self.ensure_one()
        if self.service != "qdrant" or not self._has_service_method(
            "access_capabilities"
        ):
            return {}
        return self._dispatch("access_capabilities")

    def issue_qdrant_credential(
        self, principal, grants, expires_in=None, **kwargs
    ):
        self.ensure_one()
        principal.ensure_one()
        if self.service != "qdrant" or principal.store_id != self:
            raise ValidationError(
                _("The principal must belong to this Qdrant store instance.")
            )
        if not principal.active or principal.state != "active":
            raise ValidationError(
                _("Only active Qdrant principals can receive credentials.")
            )
        if not self._has_service_method("issue_principal_credential"):
            raise UserError(_("The Qdrant adapter cannot issue credentials."))
        if any(grant.principal_id != principal for grant in grants):
            raise ValidationError(_("Every grant must belong to the principal."))
        return self._dispatch(
            "issue_principal_credential",
            principal,
            grants,
            expires_in=expires_in,
            **kwargs,
        )

    def revoke_qdrant_credential(self, credential, **kwargs):
        self.ensure_one()
        credential.ensure_one()
        if self.service != "qdrant" or credential.store_id != self:
            raise ValidationError(
                _("The credential must belong to this Qdrant store instance.")
            )
        if not self._has_service_method("revoke_principal_credential"):
            raise UserError(_("The Qdrant adapter cannot revoke credentials."))
        return self._dispatch("revoke_principal_credential", credential, **kwargs)

    def sync_qdrant_database_contract(self, database):
        self.ensure_one()
        if self.service != "qdrant" or database.store_id != self:
            return False
        if not self._has_service_method("sync_database_contract"):
            return False
        return self._dispatch("sync_database_contract", database)


class LLMStoreDatabase(models.Model):
    _inherit = "llm.store.database"

    qdrant_grant_ids = fields.One2many(
        "llm.qdrant.grant",
        "database_id",
        string="Qdrant Access Grants",
        groups="llm.group_llm_manager",
    )
    qdrant_grant_count = fields.Integer(
        compute="_compute_qdrant_grant_count",
        groups="llm.group_llm_manager",
    )

    @api.depends("qdrant_grant_ids", "qdrant_grant_ids.active")
    def _compute_qdrant_grant_count(self):
        for database in self:
            database.qdrant_grant_count = len(
                database.qdrant_grant_ids.filtered("active")
            )

    @staticmethod
    def _qdrant_default_name(database):
        return database.store_id._qdrant_sanitize_name(
            f"odoo-{database.env.cr.dbname}-{database.uuid}"
        )

    @api.constrains("store_id", "database_name", "isolation_mode")
    def _check_qdrant_collection_name(self):
        for database in self.filtered(
            lambda item: item.store_id.service == "qdrant" and item.database_name
        ):
            if self.search_count(
                [
                    ("store_id", "=", database.store_id.id),
                    ("database_name", "=", database.database_name),
                    ("id", "!=", database.id),
                ]
            ):
                raise ValidationError(
                    _(
                        "Qdrant collection '%s' is already assigned to another "
                        "database on this store.",
                        database.database_name,
                    )
                )
            if database.database_name == database.store_id._qdrant_registry_name():
                raise ValidationError(
                    _(
                        "Qdrant collection '%s' is reserved for the credential "
                        "registry.",
                        database.database_name,
                    )
                )

    @api.model_create_multi
    def create(self, vals_list):
        databases = super().create(vals_list)
        for database in databases.filtered(
            lambda item: item.store_id.service == "qdrant" and not item.database_name
        ):
            database.write({"database_name": self._qdrant_default_name(database)})
        return databases

    def action_initialize(self):
        for database in self.filtered(
            lambda item: item.store_id.service == "qdrant" and not item.database_name
        ):
            if database.state != "draft":
                raise UserError(
                    _("Set the Qdrant collection name before initializing '%s'.", database.name)
                )
            database.write({"database_name": self._qdrant_default_name(database)})
        return super().action_initialize()

    def _revoke_qdrant_database_credentials(self):
        principals = self.mapped("qdrant_grant_ids.principal_id")
        principals._revoke_active_credentials()
        return True

    def action_drop(self):
        qdrant_databases = self.filtered(
            lambda item: item.store_id.service == "qdrant"
        )
        # Validate collection ownership for every record before revoking any JWT.
        for database in qdrant_databases:
            database.store_id.database_exists(database)
        qdrant_databases._revoke_qdrant_database_credentials()
        return super().action_drop()

    def unlink(self):
        # Provisioned databases are preflighted and revoked by action_drop() in
        # the base unlink lifecycle. Draft rows have no provider cleanup phase.
        self.filtered(
            lambda item: item.store_id.service == "qdrant"
            and item.state == "draft"
            and not item.record_ids
        )._revoke_qdrant_database_credentials()
        return super().unlink()

"""PostgreSQL-specific database lifecycle policy and capability selection."""

import re
import uuid as uuid_lib

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class LLMStoreDatabase(models.Model):
    _inherit = "llm.store.database"

    state = fields.Selection(
        selection_add=[("awaiting_extensions", "Awaiting Extensions")],
        ondelete={"awaiting_extensions": "set default"},
    )
    pg_resource_mode = fields.Selection(
        [("managed", "Managed Database"), ("existing", "Existing Database")],
        default="managed",
        required=True,
        tracking=True,
    )
    pg_role_mode = fields.Selection(
        [
            ("managed", "Create Dedicated User"),
            ("existing", "Use Existing Dedicated User"),
        ],
        default="managed",
        required=True,
    )
    pg_drop_policy = fields.Selection(
        [("managed_only", "Drop Managed Resources"), ("detach", "Detach Only")],
        default="managed_only",
        required=True,
    )
    pg_template_database = fields.Char(default="template1")
    pg_partition_strategy = fields.Selection(
        [("none", "No Partitioning"), ("hash", "Hash by Record ID")],
        default="none",
        required=True,
    )
    pg_partition_count = fields.Integer(default=16)
    pg_database_created = fields.Boolean(readonly=True, copy=False)
    pg_role_created = fields.Boolean(readonly=True, copy=False)
    pg_capability_ids = fields.One2many(
        "llm.pg.database.capability", "database_id", string="Capabilities"
    )
    pg_extension_status_ids = fields.One2many(
        "llm.pg.extension.status", "database_id", string="Extension Status"
    )

    _pg_database_name_unique = models.Constraint(
        "UNIQUE(store_id, database_name)",
        "A PostgreSQL physical database can be managed only once per store.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        normalized = []
        Store = self.env["llm.store"]
        for vals in vals_list:
            values = dict(vals)
            store = Store.browse(values.get("store_id")).exists()
            if store.service == "postgresql":
                database_uuid = values.setdefault("uuid", str(uuid_lib.uuid4()))
                database_name = values.get("database_name") or (
                    f"llm_{database_uuid.replace('-', '')[:20]}"
                )
                values["database_name"] = database_name
                if (
                    values.get("pg_resource_mode", "managed") == "managed"
                    and values.get("pg_role_mode", "managed") == "managed"
                ):
                    values.setdefault("database_user", f"{database_name}_app"[:63])
            normalized.append(values)
        return super().create(normalized)

    def write(self, vals):
        structural = {
            "pg_resource_mode",
            "pg_role_mode",
            "pg_drop_policy",
            "pg_template_database",
            "pg_partition_strategy",
            "pg_partition_count",
            "database_user",
        }
        if structural.intersection(vals):
            locked = self.filtered(
                lambda database: database.store_id.service == "postgresql"
                and database.state != "draft"
            )
            if locked:
                raise UserError(
                    _("Drop the PostgreSQL database before changing provisioning settings.")
                )
        return super().write(vals)

    @api.constrains(
        "store_id",
        "database_name",
        "database_user",
        "database_secret",
        "pg_resource_mode",
        "pg_role_mode",
        "pg_partition_strategy",
        "pg_partition_count",
    )
    def _check_pg_configuration(self):
        pattern = re.compile(r"^[a-z_][a-z0-9_]*$")
        for database in self.filtered(
            lambda record: record.store_id.service == "postgresql"
        ):
            if database.isolation_mode != "database":
                raise ValidationError(
                    _("The PostgreSQL control plane currently requires database isolation.")
                )
            if not database.database_name or not pattern.fullmatch(database.database_name):
                raise ValidationError(
                    _("PostgreSQL database names must be lowercase safe identifiers.")
                )
            if len(database.database_name) > 63:
                raise ValidationError(_("PostgreSQL database names cannot exceed 63 bytes."))
            if not database.database_user:
                raise ValidationError(_("A dedicated PostgreSQL data-plane user is required."))
            if database.pg_resource_mode == "existing" and database.pg_role_mode != "existing":
                raise ValidationError(
                    _("Existing databases require an existing dedicated data-plane user.")
                )
            if (
                database.pg_resource_mode == "existing"
                and database.pg_role_mode == "existing"
                and not database.database_secret
            ):
                raise ValidationError(
                    _("Existing database users require a data-plane secret.")
                )
            if database.pg_partition_strategy == "hash" and not (
                2 <= database.pg_partition_count <= 256
            ):
                raise ValidationError(
                    _("Hash partition count must be between 2 and 256.")
                )

    def _pg_enabled_capabilities(self):
        self.ensure_one()
        return self.pg_capability_ids.filtered("enabled").sorted(
            key=lambda line: (line.capability_id.sequence, line.id)
        )

    def _pg_validate_capability_contract(self):
        self.ensure_one()
        codes = set(self._pg_enabled_capabilities().mapped("capability_id.code"))
        if (
            self.dense_embedding_model_id or self.sparse_embedding_model_id
        ) and "pgvector" not in codes:
            raise UserError(
                _("Dense and sparse PostgreSQL databases require the pgvector capability.")
            )
        lexical = {"pg_search", "pg_textsearch"}
        for query in self.query_ids.filtered("active"):
            if query.query_mode == "bm25" and not codes.intersection(lexical):
                raise UserError(_("BM25 queries require pg_search or pg_textsearch."))
            if query.query_mode == "hybrid" and query.fusion_execution == "provider":
                raise UserError(
                    _(
                        "PostgreSQL provider-side hybrid fusion is not implemented. "
                        "Use an external client query contract."
                    )
                )
        return True

    def action_initialize(self):
        postgres = self.filtered(
            lambda database: database.store_id.service == "postgresql"
        )
        other = self - postgres
        if other:
            super(LLMStoreDatabase, other).action_initialize()

        for database in postgres:
            if database.dense_embedding_model_id and not database.dimension:
                raise UserError(
                    _(
                        "Set or infer the dense vector dimension before provisioning "
                        "database '%s'.",
                        database.name,
                    )
                )
            if not database._pg_enabled_capabilities():
                raise UserError(_("Select at least one PostgreSQL capability."))
            database._pg_validate_capability_contract()
            database.write({"state": "provisioning", "last_error": False})
            try:
                result = database.store_id.provision_database(database)
                if not result:
                    raise UserError(
                        _(
                            "The PostgreSQL adapter did not provision database '%s'.",
                            database.name,
                        )
                    )
                if (
                    isinstance(result, dict)
                    and result.get("status") == "awaiting_extensions"
                ):
                    database.write(
                        {
                            "state": "awaiting_extensions",
                            "last_error": result.get("message"),
                        }
                    )
                else:
                    database.write({"state": "ready", "last_error": False})
            except Exception as error:
                # Keep failure handling in the current transaction. A second cursor
                # updating this row would wait on our own provisioning-state lock.
                database.write({"state": "error", "last_error": str(error)})
                raise
        return True

    def action_pg_probe_database(self):
        for database in self:
            if database.store_id.service != "postgresql":
                raise UserError(_("Database probing is available only for PostgreSQL."))
            database.store_id._dispatch("probe_database", database)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("PostgreSQL Probe"),
                "message": _("Target database extension status refreshed."),
                "type": "success",
                "sticky": False,
            },
        }

    def action_pg_resume_provisioning(self):
        return self.action_initialize()

"""PostgreSQL capability catalog and per-database status."""

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class LLMPgCapability(models.Model):
    _name = "llm.pg.capability"
    _description = "PostgreSQL Capability"
    _order = "sequence, code"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, index=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    component_usage = fields.Char(required=True)
    extension_names = fields.Json(default=list)
    dependency_codes = fields.Json(default=list)
    description = fields.Text(translate=True)

    _code_unique = models.Constraint(
        "UNIQUE(code)",
        "PostgreSQL capability codes must be unique.",
    )


class LLMPgDatabaseCapability(models.Model):
    _name = "llm.pg.database.capability"
    _description = "PostgreSQL Database Capability"
    _order = "capability_id, id"

    database_id = fields.Many2one(
        "llm.store.database", required=True, ondelete="cascade", index=True
    )
    capability_id = fields.Many2one(
        "llm.pg.capability", required=True, ondelete="restrict", index=True
    )
    enabled = fields.Boolean(default=True)
    configuration = fields.Json(default=dict)
    state = fields.Selection(
        [
            ("requested", "Requested"),
            ("awaiting_extension", "Awaiting Extension"),
            ("ready", "Ready"),
            ("unavailable", "Unavailable"),
            ("version_mismatch", "Version Mismatch"),
            ("error", "Error"),
        ],
        default="requested",
        required=True,
        copy=False,
    )
    installed_versions = fields.Json(readonly=True, copy=False)
    runtime_capabilities = fields.Json(readonly=True, copy=False)
    resource_metadata = fields.Json(readonly=True, copy=False)
    last_error = fields.Text(readonly=True, copy=False)
    last_checked_at = fields.Datetime(readonly=True, copy=False)

    _database_capability_unique = models.Constraint(
        "UNIQUE(database_id, capability_id)",
        "A capability can be selected only once per PostgreSQL database.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        databases = self.env["llm.store.database"].browse(
            [values.get("database_id") for values in vals_list]
        ).exists()
        if databases.filtered(lambda database: database.state != "draft"):
            raise UserError(
                _("Drop the PostgreSQL database before adding capabilities.")
            )
        return super().create(vals_list)

    def write(self, vals):
        structural = {"database_id", "capability_id", "enabled", "configuration"}
        if structural.intersection(vals) and self.mapped("database_id").filtered(
            lambda database: database.state != "draft"
        ):
            raise UserError(
                _("Drop the PostgreSQL database before changing capabilities.")
            )
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_draft_database(self):
        if self.mapped("database_id").filtered(
            lambda database: database.state != "draft"
        ):
            raise UserError(
                _("Drop the PostgreSQL database before removing capabilities.")
            )


class LLMPgExtensionStatus(models.Model):
    _name = "llm.pg.extension.status"
    _description = "PostgreSQL Extension Status"
    _order = "scope, extension_name"

    store_id = fields.Many2one(
        "llm.store", required=True, ondelete="cascade", index=True
    )
    database_id = fields.Many2one(
        "llm.store.database", ondelete="cascade", index=True
    )
    scope = fields.Selection(
        [("server", "Server"), ("database", "Database")],
        required=True,
        index=True,
    )
    extension_name = fields.Char(required=True, index=True)
    available_version = fields.Char(readonly=True)
    installed_version = fields.Char(readonly=True)
    state = fields.Selection(
        [
            ("unavailable", "Unavailable"),
            ("available_not_installed", "Available, Not Installed"),
            ("installed", "Installed"),
            ("installed_unusable", "Installed, Unusable"),
            ("version_mismatch", "Version Mismatch"),
            ("error", "Error"),
        ],
        required=True,
        default="unavailable",
        readonly=True,
    )
    details = fields.Json(readonly=True)
    checked_at = fields.Datetime(readonly=True)

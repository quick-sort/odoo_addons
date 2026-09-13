"""Persistent ownership map between Odoo chunks and provider records.

A chunk is logical source/build output and may be imported into several store
databases. Provider IDs therefore cannot live on ``llm.store.chunk`` itself.
This model records one database + chunk binding and is the only place where a
provider-side ID is associated with an Odoo chunk.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_RECORD_MUTATION_CONTEXT = "allow_database_record_mutation"


class LLMStoreDatabaseRecord(models.Model):
    _name = "llm.store.database.record"
    _description = "LLM Store Database Record"
    _order = "database_id, chunk_id, id"

    name = fields.Char(compute="_compute_name", store=True)
    database_id = fields.Many2one(
        "llm.store.database",
        required=True,
        ondelete="cascade",
        index=True,
    )
    chunk_id = fields.Many2one(
        "llm.store.chunk",
        required=True,
        ondelete="restrict",
        index=True,
        help="Odoo chunk represented by this provider-side record.",
    )
    logical_id = fields.Char(
        required=True,
        copy=False,
        index=True,
        help="Stable provider-independent ID for this database/chunk binding.",
    )
    backend_id = fields.Char(
        required=True,
        copy=False,
        index=True,
        help="Actual point/row/document ID used by the provider.",
    )
    content_checksum = fields.Char(index=True)
    payload_checksum = fields.Char(index=True)
    state = fields.Selection(
        selection=[
            ("pending", "Pending"),
            ("synced", "Synced"),
            ("deleting", "Deleting"),
            ("error", "Error"),
        ],
        required=True,
        default="pending",
        index=True,
    )
    active = fields.Boolean(default=True, index=True)
    synced_once = fields.Boolean(
        default=False,
        copy=False,
        help="Whether this mapping has completed at least one provider upsert.",
    )
    provider_metadata = fields.Json()
    last_error = fields.Text(copy=False)

    _unique_chunk = models.Constraint(
        "UNIQUE(database_id, chunk_id)",
        "A chunk can have only one provider record per database.",
    )
    _unique_logical_id = models.Constraint(
        "UNIQUE(database_id, logical_id)",
        "Logical record IDs must be unique per database.",
    )
    _unique_backend_id = models.Constraint(
        "UNIQUE(database_id, backend_id)",
        "Provider record IDs must be unique per database.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get(_RECORD_MUTATION_CONTEXT):
            raise UserError(_("Provider mappings are managed by store databases."))
        return super().create(vals_list)

    def write(self, vals):
        if vals and not self.env.context.get(_RECORD_MUTATION_CONTEXT):
            raise UserError(_("Provider mappings are managed by store databases."))
        return super().write(vals)

    def unlink(self):
        if not self.env.context.get(_RECORD_MUTATION_CONTEXT):
            raise UserError(_("Provider mappings can only be removed by cleanup."))
        return super().unlink()

    @api.constrains("database_id", "chunk_id")
    def _check_database_chunkset(self):
        for record in self:
            if (
                record.database_id
                and record.chunk_id
                and record.chunk_id.chunkset_id != record.database_id.chunkset_id
            ):
                raise ValidationError(
                    _("A provider record must use its database's chunking method.")
                )

    @api.depends("database_id.name", "chunk_id.name")
    def _compute_name(self):
        for record in self:
            record.name = "%s / %s" % (
                record.database_id.name or "Database",
                record.chunk_id.name or "Chunk",
            )

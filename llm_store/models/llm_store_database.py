"""A physical knowledge database hosted by an ``llm.store`` instance.

The instance is the administrative/control-plane boundary.  This model is the
isolated data-plane resource: it belongs to exactly one knowledge collection
and records one complete import/build method (splitter, embedding model and
backend index configuration).  Several databases may therefore be built from
the same knowledge collection and benchmarked independently.
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class LLMStoreDatabase(models.Model):
    _name = "llm.store.database"
    _description = "LLM Store Database"
    _inherit = ["llm.store.collection"]
    _order = "store_id, name, id"

    knowledge_collection_id = fields.Many2one(
        "llm.knowledge.collection",
        string="Knowledge Collection",
        required=True,
        ondelete="restrict",
        index=True,
        tracking=True,
        help="The single logical knowledge collection stored in this database.",
    )
    chunkset_id = fields.Many2one(
        "llm.knowledge.chunkset",
        string="Chunking Configuration",
        required=True,
        ondelete="restrict",
        index=True,
        tracking=True,
        domain="[('collection_id', '=', knowledge_collection_id)]",
        help="The splitting method used to build this database.",
    )
    embedding_model_id = fields.Many2one(
        "llm.model",
        string="Embedding Model",
        required=True,
        ondelete="restrict",
        tracking=True,
        domain="[('model_use', '=', 'embedding')]",
    )

    # A stable database-owned key decouples backend resource names from
    # vector/build execution records.
    backend_key = fields.Char(copy=False, readonly=True, index=True)
    database_name = fields.Char(
        string="Backend Database Name",
        help="Optional provider-specific database, collection, schema or index name.",
    )
    connection_uri = fields.Char(
        string="Database Connection URI",
        help="Optional data-plane endpoint when it differs from the instance endpoint.",
    )
    database_user = fields.Char(
        help="Optional child/service account created for this database.",
    )
    database_secret = fields.Char(
        copy=False,
        help="Credential for the database child/service account.",
    )
    index_configuration = fields.Json(
        help="Backend-specific index and tuning parameters for this build variant.",
    )
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("provisioning", "Provisioning"),
            ("ready", "Ready"),
            ("error", "Error"),
        ],
        default="draft",
        required=True,
        copy=False,
        tracking=True,
    )
    last_error = fields.Text(readonly=True, copy=False)
    vector_ids = fields.One2many(
        "llm.knowledge.vector",
        "database_id",
        string="Build Configuration",
    )
    build_count = fields.Integer(compute="_compute_build_count")

    _unique_backend_key_per_store = models.Constraint(
        "UNIQUE(store_id, backend_key)",
        "Backend database keys must be unique per store instance.",
    )

    @api.depends("vector_ids")
    def _compute_build_count(self):
        for database in self:
            database.build_count = len(database.vector_ids)

    @api.constrains(
        "knowledge_collection_id",
        "chunkset_id",
        "embedding_model_id",
        "dimension",
    )
    def _check_build_method(self):
        for database in self:
            if (
                database.chunkset_id
                and database.chunkset_id.collection_id
                != database.knowledge_collection_id
            ):
                raise ValidationError(
                    _(
                        "Chunking configuration '%(chunkset)s' does not belong to "
                        "knowledge collection '%(collection)s'.",
                        chunkset=database.chunkset_id.name,
                        collection=database.knowledge_collection_id.name,
                    )
                )
            if (
                database.embedding_model_id
                and database.embedding_model_id.model_use != "embedding"
            ):
                raise ValidationError(
                    _(
                        "Model '%s' is not an embedding model.",
                        database.embedding_model_id.name,
                    )
                )
            if database.dimension and database.dimension <= 0:
                raise ValidationError(_("Vector dimension must be a positive integer."))

    @api.model_create_multi
    def create(self, vals_list):
        databases = super().create(vals_list)
        for database in databases.filtered(lambda record: not record.backend_key):
            database.with_context(allow_backend_key_write=True).write(
                {"backend_key": str(database.id)}
            )
        return databases

    def write(self, vals):
        if "backend_key" in vals and not self.env.context.get(
            "allow_backend_key_write"
        ):
            raise UserError(_("The backend database key is immutable."))

        method_fields = {
            "store_id",
            "knowledge_collection_id",
            "chunkset_id",
            "embedding_model_id",
            "dimension",
            "database_name",
            "index_configuration",
        }
        if method_fields.intersection(vals):
            provisioned = self.filtered(lambda database: database.state != "draft")
            if provisioned:
                raise UserError(
                    _(
                        "Drop provisioned databases before changing their instance, "
                        "knowledge collection, or build method."
                    )
                )
            if "embedding_model_id" in vals:
                vals = dict(vals, dimension=False)

        result = super().write(vals)
        if method_fields.intersection(vals):
            self.mapped("vector_ids").write({"state": "draft"})
        return result

    def copy_data(self, default=None):
        default = dict(default or {}, backend_key=False, state="draft", last_error=False)
        return super().copy_data(default=default)

    def _backend_metadata(self):
        """Return non-secret provisioning metadata for compatibility adapters."""
        self.ensure_one()
        metadata = dict(self.metadata or {})
        metadata.update(self.index_configuration or {})
        if self.database_name:
            metadata["database_name"] = self.database_name
        return metadata

    def _ensure_vector(self):
        """Return this database's single build execution record."""
        self.ensure_one()
        vector = self.vector_ids[:1]
        if vector:
            return vector
        return self.env["llm.knowledge.vector"].create(
            {"database_id": self.id, "is_default": False}
        )

    def action_initialize(self):
        """Provision this database through the instance administrator adapter."""
        for database in self:
            if not database.dimension:
                raise UserError(
                    _(
                        "Set or infer the embedding dimension before provisioning "
                        "database '%s'.",
                        database.name,
                    )
                )
            database.write({"state": "provisioning", "last_error": False})
            try:
                if not database.store_id.database_exists(database):
                    created = database.store_id.provision_database(database)
                    if not created:
                        raise UserError(
                            _("The store adapter did not provision database '%s'.", database.name)
                        )
                database.write({"state": "ready", "last_error": False})
            except Exception as error:
                database.write({"state": "error", "last_error": str(error)})
                raise
        return True

    def action_drop(self):
        """Drop the physical database; the Odoo configuration remains reusable."""
        for database in self:
            try:
                if database.store_id.database_exists(database):
                    dropped = database.store_id.drop_database(database)
                    if dropped is False:
                        raise UserError(
                            _("The store adapter did not drop database '%s'.", database.name)
                        )
                database.write({"state": "draft", "last_error": False})
                database.vector_ids.write({"state": "draft"})
            except Exception as error:
                database.write({"state": "error", "last_error": str(error)})
                raise
        return True

    def action_build(self):
        """Build this database from its configured knowledge collection."""
        for database in self:
            database._ensure_vector().action_build()
        return True

    def action_rebuild(self):
        """Drop and rebuild this isolated database variant."""
        for database in self:
            database.action_drop()
            database.action_build()
        return True

    def unlink(self):
        for database in self.filtered(lambda record: record.state != "draft"):
            # Cleanup failures deliberately block deletion so ownership of a
            # remote resource is never lost from Odoo.
            database.action_drop()
        return super().unlink()

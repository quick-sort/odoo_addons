from odoo import api, fields, models

from odoo.addons.base_pgvector.fields import PgVector


class LLMKnowledgeChunkEmbedding(models.Model):
    _name = "llm.knowledge.chunk.embedding"
    _description = "Vector Embedding for Knowledge Chunks"
    _rec_name = "chunk_id"

    chunk_id = fields.Many2one(
        "llm.store.chunk", required=True, ondelete="cascade", index=True
    )
    vector_id = fields.Many2one(
        "llm.knowledge.vector",
        required=True,
        ondelete="cascade",
        index=True,
    )
    collection_id = fields.Many2one(
        "llm.knowledge.collection",
        related="vector_id.collection_id",
        store=False,
        readonly=True,
    )
    embedding_model_id = fields.Many2one(
        "llm.model",
        domain="[('model_use', '=', 'embedding')]",
        required=True,
        ondelete="restrict",
        index=True,
    )
    embedding = PgVector(
        string="Vector Embedding", help="Vector embedding for similarity search"
    )
    content = fields.Text(readonly=True)
    metadata = fields.Json(default=dict, readonly=True)
    document_id = fields.Many2one(
        related="chunk_id.document_id", store=True, readonly=True, index=True
    )

    _unique_chunk_vector = models.Constraint(
        "UNIQUE(chunk_id, vector_id)",
        "A chunk can only have one embedding per vector configuration.",
    )

    display_name = fields.Char(compute="_compute_display_name")

    @api.depends("chunk_id.name", "vector_id.name")
    def _compute_display_name(self):
        for record in self:
            record.display_name = "%s [%s]" % (
                record.chunk_id.name or "Chunk",
                record.vector_id.name or "Vector",
            )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("vector_id") and not vals.get("embedding_model_id"):
                vector = self.env["llm.knowledge.vector"].browse(vals["vector_id"])
                vals["embedding_model_id"] = vector.embedding_model_id.id
        return super().create(vals_list)

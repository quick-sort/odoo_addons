# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

"""A vector store configuration: a chunkset + embedding model + external
vector store + dimensionality. One KB can hold several of these (different
models / stores) to compare retrieval quality.
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class KnowledgeVector(models.Model):
    _name = "knowledge.vector"
    _description = "Knowledge Vector Store Configuration"
    _inherit = ["mail.thread"]

    name = fields.Char(required=True)
    chunkset_id = fields.Many2one(
        comodel_name="knowledge.chunkset",
        string="Chunking Configuration",
        required=True,
        ondelete="cascade",
        index=True,
    )
    model_id = fields.Many2one(
        comodel_name="llm.model",
        string="Embedding Model",
        required=True,
        ondelete="restrict",
        domain="[('model_use', '=', 'embedding')]",
    )
    vector_store_id = fields.Many2one(
        comodel_name="knowledge.vector.store",
        string="Vector Store",
        required=True,
        ondelete="restrict",
    )
    vector_size = fields.Integer(
        required=True,
        help="Dimensionality of the embedding vectors.",
    )
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("building", "Building"),
            ("vectorized", "Vectorized"),
            ("error", "Error"),
        ],
        default="draft",
        tracking=True,
    )
    chunk_count = fields.Integer(
        compute="_compute_chunk_count",
        string="Vectorized Chunks",
    )

    @api.depends("chunkset_id.chunk_ids")
    def _compute_chunk_count(self):
        for vector in self:
            vector.chunk_count = len(vector.chunkset_id.chunk_ids)

    @api.constrains("vector_size", "model_id")
    def _check_vector_size(self):
        for vector in self:
            if vector.vector_size <= 0:
                raise ValidationError(
                    _("Vector size must be a positive integer.")
                )
            if vector.model_id.model_use != "embedding":
                raise ValidationError(
                    _("Model '%s' is not an embedding model.", vector.model_id.name)
                )

    # ------------------------------------------------------------------
    # Vectorization workflow
    # ------------------------------------------------------------------
    def _index_name(self):
        """Name of the index/collection inside the external vector store."""
        self.ensure_one()
        return "kb_%s_cs_%s" % (self.chunkset_id.kb_id.id, self.chunkset_id.id)

    def action_build(self):
        """Enqueue the vectorization job (async)."""
        for vector in self:
            vector.with_delay(
                channel="root.knowledge",
                description=_("Vectorize %s") % vector.name,
            )._vectorize()
        return True

    def _vectorize(self):
        """Embed every chunk of the chunkset and store it. Queue job body."""
        self.ensure_one()
        chunkset = self.chunkset_id
        if not chunkset.chunk_ids:
            raise UserError(
                _("Chunkset '%s' has no chunks yet. Run chunking first.", chunkset.name)
            )
        self.write({"state": "building"})
        try:
            kb = chunkset.kb_id
            client = self.vector_store_id._get_client()
            index = self._index_name()
            client.ensure_index(index, self.vector_size)
            points = []
            for chunk in chunkset.chunk_ids:
                text = chunk._read_text()
                vector = self.model_id.embedding([text])[0]
                points.append(
                    (
                        str(chunk.id),
                        vector,
                        {
                            "kb_id": kb.id,
                            "source_id": chunk.source_id.id,
                            "chunkset_id": chunkset.id,
                            "chunk_id": chunk.id,
                            "chunk_path": chunk.path,
                            "sequence": chunk.sequence,
                        },
                    )
                )
            if points:
                client.upsert(index, points)
            self.write({"state": "vectorized"})
            kb._refresh_state()
        except Exception:
            _logger.exception("Vectorization failed for %s", self.name)
            self.write({"state": "error"})
            raise

    def action_drop(self):
        """Delete the external index/collection and reset to draft."""
        for vector in self:
            client = vector.vector_store_id._get_client()
            if client is not None:
                try:
                    client.drop_index(vector._index_name())
                except Exception:  # noqa: BLE001
                    _logger.warning("Could not drop index %s", vector._index_name())
            vector.write({"state": "draft"})
        return True

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------
    def search_similar(self, query, limit=10):
        """Embed ``query`` and return the most similar chunks with their text.

        Returns a list of dicts::

            {
                "chunk_id", "source_id", "chunk_path", "score", "text",
            }
        """
        self.ensure_one()
        if self.state != "vectorized":
            raise UserError(
                _("Vector store '%s' has not been built yet.", self.name)
            )
        vector = self.model_id.embedding([query])[0]
        client = self.vector_store_id._get_client()
        hits = client.search(self._index_name(), vector, limit=limit)
        backend = self.chunkset_id.kb_id.md_backend_id
        results = []
        for hit in hits:
            payload = hit.get("payload") or {}
            text = ""
            if payload.get("chunk_path"):
                try:
                    text = backend.get(payload["chunk_path"]).decode("utf-8")
                except Exception:  # noqa: BLE001
                    text = ""
            results.append(
                {
                    "chunk_id": payload.get("chunk_id"),
                    "source_id": payload.get("source_id"),
                    "chunk_path": payload.get("chunk_path"),
                    "score": hit.get("score"),
                    "text": text,
                }
            )
        return results

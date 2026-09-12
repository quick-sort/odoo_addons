"""One chunking method that may be selected by store databases.

A knowledge collection may have several chunksets. Each physical
``llm.store.database`` selects exactly one chunkset together with one embedding
model and its own backend index configuration. This lets the same source
collection be built into multiple isolated databases and benchmarked without
mixing methods or duplicating chunk text in Odoo.

Chunking and vectorization are fused during a database build: text is produced
in memory, embedded, then persisted as backend payload. ``llm.store.chunk``
remains a pointer-only row.
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class LLMKnowledgeChunkset(models.Model):
    _name = "llm.knowledge.chunkset"
    _description = "LLM Knowledge Chunking Configuration"
    _inherit = ["mail.thread"]
    _order = "sequence, id"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    collection_id = fields.Many2one(
        "llm.knowledge.collection",
        string="Collection",
        required=True,
        ondelete="cascade",
        index=True,
    )
    splitter_id = fields.Many2one(
        "llm.knowledge.splitter",
        string="Splitter",
        required=True,
        ondelete="restrict",
    )
    is_default = fields.Boolean(
        default=False,
        help="Used as the default chunking configuration for this "
        "collection's plain-text vector search when no chunkset is "
        "explicitly requested.",
    )
    active = fields.Boolean(default=True)
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("chunking", "Chunking"),
            ("chunked", "Chunked"),
            ("error", "Error"),
        ],
        default="draft",
        tracking=True,
    )
    chunk_ids = fields.One2many(
        "llm.store.chunk",
        "chunkset_id",
        string="Chunks",
    )
    chunk_count = fields.Integer(compute="_compute_chunk_count")
    vector_ids = fields.One2many(
        "llm.knowledge.vector",
        "chunkset_id",
        string="Database Builds",
    )
    vector_count = fields.Integer(compute="_compute_vector_count")

    @api.depends("chunk_ids")
    def _compute_chunk_count(self):
        for chunkset in self:
            chunkset.chunk_count = len(chunkset.chunk_ids)

    @api.depends("vector_ids")
    def _compute_vector_count(self):
        for chunkset in self:
            chunkset.vector_count = len(chunkset.vector_ids)

    @api.constrains("collection_id", "is_default")
    def _check_single_default(self):
        for chunkset in self:
            if not chunkset.is_default:
                continue
            others = self.search(
                [
                    ("collection_id", "=", chunkset.collection_id.id),
                    ("is_default", "=", True),
                    ("id", "!=", chunkset.id),
                ]
            )
            if others:
                raise UserError(
                    _(
                        "Collection '%s' already has a default chunkset.",
                        chunkset.collection_id.name,
                    )
                )

    # ------------------------------------------------------------------
    # Chunk-pointer bookkeeping (no text stored; see llm.knowledge.vector
    # for the actual split+embed+upsert pipeline)
    # ------------------------------------------------------------------
    def _split_document(self, document_record):
        """Split ``document_record``'s markdown content with this chunkset's
        splitter and return the resulting list of chunk texts (transient,
        never persisted -- callers pass these straight to embedding)."""
        self.ensure_one()
        document = document_record.get_processed_document()
        text = document["markdown"]
        if not text:
            return []
        return self.splitter_id.split(
            text, document_record=document_record, document=document
        )

    def _sync_chunk_pointers(self, document_record, chunk_texts):
        """Ensure exactly ``len(chunk_texts)`` pointer rows exist for
        ``(chunkset, document_record)``, in sequence order. Returns the chunk
        recordset in the same order as ``chunk_texts``."""
        self.ensure_one()
        existing = self.env["llm.store.chunk"].search(
            [("chunkset_id", "=", self.id), ("document_id", "=", document_record.id)],
            order="sequence",
        )
        target_count = len(chunk_texts)
        if len(existing) > target_count:
            existing[target_count:].unlink()
            existing = existing[:target_count]
        chunks = list(existing)
        for seq in range(len(chunks) + 1, target_count + 1):
            chunks.append(
                self.env["llm.store.chunk"].create(
                    {
                        "chunkset_id": self.id,
                        "document_id": document_record.id,
                        "sequence": seq,
                    }
                )
            )
        return self.env["llm.store.chunk"].browse([chunk.id for chunk in chunks])

    def action_chunk(self):
        """Recompute chunk pointers for every document in the collection.

        This only maintains pointer rows (id/sequence bookkeeping); it does
        not embed anything. Embedding (which is when chunk text actually
        gets produced and sent to a vector store) happens per
        ``llm.knowledge.vector`` via ``action_build``, which re-splits and
        re-syncs pointers itself -- so calling this directly is mostly
        useful to preview chunk counts before configuring a vector.
        """
        for chunkset in self:
            chunkset.write({"state": "chunking"})
            try:
                for document_record in chunkset.collection_id.document_ids:
                    if document_record.state not in ("processed", "chunked", "ready"):
                        continue
                    chunk_texts = chunkset._split_document(document_record)
                    chunkset._sync_chunk_pointers(document_record, chunk_texts)
                chunkset.write({"state": "chunked"})
            except Exception:
                _logger.exception("Chunking failed for chunkset %s", chunkset.name)
                chunkset.write({"state": "error"})
                raise

    def action_view_chunks(self):
        self.ensure_one()
        return {
            "name": _("Chunks"),
            "view_mode": "list,form",
            "res_model": "llm.store.chunk",
            "domain": [("chunkset_id", "=", self.id)],
            "type": "ir.actions.act_window",
        }

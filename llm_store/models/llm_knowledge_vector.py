"""A vector configuration: one chunkset x one embedding model x one vector
store. A chunkset can hold several of these (different models, different
dimensions, different stores) so retrieval quality can be compared across
configurations without duplicating chunk text in Odoo -- chunk text lives
only inside the vector store, as payload alongside its embedding (see
module docstring on llm.store.chunk for the rationale).

Inherits ``llm.store.collection`` (store_id, dimension, insert_vectors,
search_vectors, delete_vectors) to reuse the store adapters (pgvector,
pgvector_local, qdrant) unchanged.
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class LLMKnowledgeVector(models.Model):
    _name = "llm.knowledge.vector"
    _description = "LLM Knowledge Vector Configuration"
    _inherit = ["llm.store.collection"]
    _order = "id"

    chunkset_id = fields.Many2one(
        "llm.knowledge.chunkset",
        string="Chunking Configuration",
        required=True,
        ondelete="cascade",
        index=True,
    )
    collection_id = fields.Many2one(
        "llm.knowledge.collection",
        string="Collection",
        related="chunkset_id.collection_id",
        store=True,
        readonly=True,
        index=True,
    )
    embedding_model_id = fields.Many2one(
        "llm.model",
        string="Embedding Model",
        required=True,
        ondelete="restrict",
        domain="[('model_use', '=', 'embedding')]",
    )
    is_default = fields.Boolean(
        default=False,
        help="Used as the default vector configuration for this "
        "collection's plain-text vector search when no vector is "
        "explicitly requested.",
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

    @api.constrains("dimension", "embedding_model_id")
    def _check_dimension(self):
        for vector in self:
            if vector.dimension and vector.dimension <= 0:
                raise ValidationError(_("Vector dimension must be a positive integer."))
            if (
                vector.embedding_model_id
                and vector.embedding_model_id.model_use != "embedding"
            ):
                raise ValidationError(
                    _(
                        "Model '%s' is not an embedding model.",
                        vector.embedding_model_id.name,
                    )
                )

    @api.model_create_multi
    def create(self, vals_list):
        vectors = super().create(vals_list)
        for vector in vectors:
            if vector.store_id:
                vector._initialize_store()
        return vectors

    def unlink(self):
        for vector in self:
            if vector.store_id:
                try:
                    vector.store_id.delete_collection(vector.id)
                except Exception:  # noqa: BLE001
                    _logger.warning(
                        "Error deleting store collection for vector %s", vector.id
                    )
        return super().unlink()

    def _initialize_store(self):
        self.ensure_one()
        if not self.store_id:
            return False
        if not self.store_id.collection_exists(self.id):
            created = self.store_id.create_collection(self.id, dimension=self.dimension)
            if not created:
                raise UserError(
                    _("Failed to create collection in store for vector '%s'.", self.name)
                )
        return True

    def action_drop(self):
        for vector in self:
            if vector.store_id and vector.store_id.collection_exists(vector.id):
                try:
                    vector.store_id.delete_collection(vector.id)
                except Exception:  # noqa: BLE001
                    _logger.warning("Could not drop store collection for %s", vector.id)
            vector.write({"state": "draft"})
        return True

    # ------------------------------------------------------------------
    # Build: split (transient) -> embed -> insert, text travels as payload
    # ------------------------------------------------------------------
    def action_build(self, specific_document_ids=None):
        """Chunk and embed every document of this vector's collection (or
        only ``specific_document_ids``) into the vector store, in one pass
        per document: split -> embed -> insert_vectors(metadata={"text":...}).
        Chunk pointer rows are created/kept in sync as a side effect but
        never carry the text themselves.
        """
        for vector in self:
            vector.write({"state": "building"})
            try:
                vector._initialize_store()
                chunkset = vector.chunkset_id
                documents = chunkset.collection_id.document_ids
                if specific_document_ids:
                    documents = documents.filtered(
                        lambda r: r.id in specific_document_ids
                    )
                documents = documents.filtered(
                    lambda r: r.state in ("processed", "chunked", "ready")
                )
                total_chunks = 0
                for document_record in documents:
                    total_chunks += vector._build_document(chunkset, document_record)
                vector.write({"state": "vectorized"})
                _logger.info(
                    "Vector '%s': embedded %d chunks from %d documents.",
                    vector.name,
                    total_chunks,
                    len(documents),
                )
            except Exception:
                _logger.exception("Vectorization failed for vector %s", vector.name)
                vector.write({"state": "error"})
                raise

    def _build_document(self, chunkset, document_record):
        """Split + embed + insert one document record's chunks for this vector.
        Returns the number of chunks processed."""
        self.ensure_one()
        chunk_texts = chunkset._split_document(document_record)
        if not chunk_texts:
            return 0
        chunks = chunkset._sync_chunk_pointers(document_record, chunk_texts)

        vectors = self.embedding_model_id.embedding(chunk_texts)
        if not self.dimension and vectors:
            self.dimension = len(vectors[0])
            self._initialize_store()

        document = document_record.get_processed_document()
        metadata_list = []
        for chunk, text in zip(chunks, chunk_texts):  # noqa: B905
            payload = dict(document["metadata"])
            payload.update(
                {
                    "text": text,
                    "title": document["title"],
                    "source_uri": document["source_uri"],
                    "mimetype": document["mimetype"],
                    "filename": document["filename"],
                    "checksum": document["checksum"],
                    "document_id": document_record.id,
                    "document_name": document_record.name,
                    "collection_id": document_record.collection_id.id,
                    "chunk_id": chunk.id,
                    "chunkset_id": chunkset.id,
                    "sequence": chunk.sequence,
                }
            )
            metadata_list.append(payload)
        self.insert_vectors(
            vectors=vectors,
            metadata=metadata_list,
            ids=chunks.ids,
        )
        return len(chunks)

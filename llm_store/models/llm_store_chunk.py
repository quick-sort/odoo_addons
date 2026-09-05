import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class LLMStoreChunk(models.Model):
    """A chunk is a pointer/metadata row only: (resource, chunkset,
    sequence). The chunk's text is never stored in Odoo's database, and
    never written to a storage backend either -- it is produced transiently
    during splitting (llm.knowledge.chunkset._split_resource), embedded
    immediately, and persisted as payload alongside its vector inside the
    vector store (llm.knowledge.vector._build_resource / insert_vectors).

    ``content`` is only populated transiently on records returned by
    ``search()`` with an 'embedding' domain term (see
    ``_vector_search_aggregate`` below), which carries the text back from
    the search hit's payload via context. It is otherwise empty for chunks
    fetched by plain browse()/search() -- there is nowhere else to read it
    from.
    """

    _name = "llm.store.chunk"
    _description = "Document Chunk for RAG"
    _order = "sequence, id"

    _unique_chunk_position = models.Constraint(
        "UNIQUE(chunkset_id, resource_id, sequence)",
        "A chunk already exists at this position for this chunkset/resource.",
    )

    name = fields.Char(
        string="Name",
        compute="_compute_name",
        store=True,
    )
    resource_id = fields.Many2one(
        "llm.resource",
        string="Resource",
        required=True,
        ondelete="cascade",
        index=True,
    )
    chunkset_id = fields.Many2one(
        "llm.knowledge.chunkset",
        string="Chunking Configuration",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer(
        string="Sequence",
        default=10,
        help="Order of the chunk within the resource, for this chunkset",
    )
    content = fields.Text(
        string="Content",
        store=False,
        compute="_compute_content",
        help="Chunk text is not stored in Odoo -- it lives in the vector "
        "store as payload alongside its embedding (see "
        "llm.knowledge.vector._build_resource). This field is only "
        "populated transiently on records returned by a vector search "
        "(llm.store.chunk.search() with an 'embedding' domain term), "
        "which carries the text back from the search hit's payload via "
        "context; it is otherwise empty for chunks fetched by plain "
        "browse()/search().",
    )
    metadata = fields.Json(
        string="Metadata",
        default={},
        help="Additional metadata for this chunk",
    )
    # Related field to resource collections
    collection_ids = fields.Many2many(
        "llm.knowledge.collection",
        string="Collections",
        related="resource_id.collection_ids",
        store=False,
    )
    # Virtual field for vector search input
    # This field is handled by the search() method override
    embedding = fields.Char(
        string="Embedding",
        store=False,
        search="_search_embedding",
    )

    # Virtual field to store similarity score in search results
    similarity = fields.Float(
        string="Similarity Score", store=False, compute="_compute_similarity"
    )

    def _search_embedding(self, operator, value):
        """Search method for the embedding field.

        This is called by Odoo's domain parser when it encounters an embedding field in the domain.
        We store the search term in context and return an always-true domain.
        The actual vector search is handled by the search() method override.
        """
        # Store search term in context for search() to pick up
        self.env.context = dict(self.env.context, _embedding_search_term=value)

        # Return always-true domain (search() will handle the actual filtering)
        return [("id", ">", 0)]

    @api.depends("resource_id.name", "sequence")
    def _compute_name(self):
        for chunk in self:
            if chunk.resource_id and chunk.resource_id.name:
                chunk.name = f"{chunk.resource_id.name} - Chunk {chunk.sequence}"
            else:
                chunk.name = f"Chunk {chunk.sequence}"

    def _compute_similarity(self):
        """Compute method for the similarity field."""
        for record in self:
            # Get the similarity score from the context
            record.similarity = self.env.context.get("similarity_scores", {}).get(
                record.id, 0.0
            )

    def _compute_content(self):
        """Populate chunk text from the context stash set by
        _vector_search_aggregate(); empty for records fetched normally."""
        texts = self.env.context.get("chunk_texts", {})
        for record in self:
            record.content = texts.get(record.id, "")

    def open_chunk_detail(self):
        """Open a form view of the chunk for detailed viewing."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "llm.store.chunk",
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def get_collection_embedding_models(self):
        """Helper method to get embedding models used by vectors of this
        chunk's chunkset."""
        self.ensure_one()
        return self.chunkset_id.vector_ids.mapped("embedding_model_id")

    def unlink(self):
        """Override unlink to remove vectors from vector stores before deleting chunks"""
        # Group chunks by chunkset for efficient processing
        chunks_by_chunkset = {}
        for chunk in self:
            chunks_by_chunkset.setdefault(
                chunk.chunkset_id.id, self.env["llm.store.chunk"]
            )
            chunks_by_chunkset[chunk.chunkset_id.id] |= chunk

        # Remove vectors from each chunkset's vector configurations
        for chunkset_id, chunks in chunks_by_chunkset.items():
            chunkset = self.env["llm.knowledge.chunkset"].browse(chunkset_id)
            for vector in chunkset.vector_ids:
                if not vector.store_id:
                    continue
                try:
                    vector.delete_vectors(ids=chunks.ids)
                    _logger.info(
                        f"Removed {len(chunks)} vectors from vector config {vector.name} (ID: {vector.id})"
                    )
                except Exception as e:
                    _logger.warning(
                        f"Error removing vectors for chunks from vector config {vector.name} (ID: {vector.id}): {str(e)}"
                    )

        # Proceed with standard deletion
        return super().unlink()

    def _has_vector_search(self, domain, vector_search_term=None, query_vector=None):
        """Check if vector search should be performed.

        Args:
            domain: Search domain
            vector_search_term: Explicit search term from kwargs
            query_vector: Pre-computed query vector from kwargs

        Returns:
            bool: True if vector search should be performed
        """
        has_embedding = any(
            isinstance(arg, (list, tuple)) and len(arg) == 3 and arg[0] == "embedding"
            for arg in domain
        )
        has_context_search = self.env.context.get("_embedding_search_term")
        return bool(
            has_embedding or has_context_search or vector_search_term or query_vector
        )

    def _parse_vector_search_domain(self, domain):
        """Parse domain to extract vector search term and filter out embedding clauses.

        Returns:
            tuple: (vector_search_term, filtered_domain)
                - vector_search_term: str or None
                - filtered_domain: list of domain clauses without embedding
        """
        vector_search_term = self.env.context.get("_embedding_search_term")
        filtered_domain = []

        for arg in domain:
            if (
                isinstance(arg, (list, tuple))
                and len(arg) == 3
                and arg[0] == "embedding"
                and isinstance(arg[2], str)
            ):
                vector_search_term = arg[2]
            else:
                filtered_domain.append(arg)

        return vector_search_term, filtered_domain

    def _get_vector_search_vectors(self, vector_search_term, query_vector, vector_id):
        """Get llm.knowledge.vector configurations eligible for vector
        search.

        Args:
            vector_search_term: free-text query to embed, or None
            query_vector: a pre-computed query vector, or None
            vector_id: optional llm.knowledge.vector id to restrict to

        Returns:
            llm.knowledge.vector recordset
        """
        Vector = self.env["llm.knowledge.vector"]

        if vector_id:
            vector = Vector.browse(vector_id)
            if (
                vector.exists()
                and vector.store_id
                and (query_vector or vector.embedding_model_id)
            ):
                return vector
            return Vector

        domain = [
            ("active", "=", True),
            ("store_id", "!=", False),
            ("state", "=", "vectorized"),
        ]
        if vector_search_term and not query_vector:
            domain.append(("embedding_model_id", "!=", False))
        return Vector.search(domain)

    def _generate_embeddings_for_vectors(self, vectors, vector_search_term):
        """Generate embeddings for the search term across vectors'
        embedding models.

        Returns:
            tuple: (model_vector_map, filtered_vectors)
        """
        model_vector_map = {}
        embedding_models = vectors.mapped("embedding_model_id")

        if not embedding_models:
            return model_vector_map, vectors

        for model in embedding_models:
            try:
                model_vector_map[model.id] = model.embedding(
                    vector_search_term.strip()
                )[0]
            except Exception:
                # Remove vectors using this failed model
                vectors = vectors.filtered(
                    lambda v, failed_model_id=model.id: v.embedding_model_id.id
                    != failed_model_id
                )

        return model_vector_map, vectors

    @api.model
    def search_fetch(self, domain, field_names, offset=0, limit=None, order=None):
        """Override search_fetch to use our search() method when vector search is involved."""
        if self._has_vector_search(domain):
            # Call our search() override which handles vector search
            records = self.search(domain, offset=offset, limit=limit, order=order)

            # Fetch the fields
            if field_names:
                records.fetch(field_names)

            return records
        else:
            # No vector search, use standard implementation
            return super().search_fetch(
                domain, field_names, offset=offset, limit=limit, order=order
            )

    @api.model
    def search(self, args, offset=0, limit=None, order=None, **kwargs):
        count = kwargs.pop("count", False)

        # Parse domain to extract vector search term and remove embedding clauses
        vector_search_term, search_args = self._parse_vector_search_domain(args)

        # Override with explicit vector_search_term from kwargs if provided
        if "vector_search_term" in kwargs:
            vector_search_term = kwargs["vector_search_term"]

        query_vector = kwargs.get("query_vector")
        specific_vector_id = kwargs.get("vector_id") or kwargs.get("collection_id")
        if query_vector and not specific_vector_id:
            raise UserError(
                _(
                    "A pre-computed 'query_vector' can only be used when a specific 'vector_id' is also provided."
                    " Searching across multiple vector configurations requires a 'vector_search_term' for model-specific embedding generation."
                )
            )

        if not self._has_vector_search(args, vector_search_term, query_vector):
            if count:
                return super().search_count(search_args)
            return super().search(
                search_args,
                offset=offset,
                limit=limit,
                order=order,
                **kwargs,
            )

        # Get eligible vector configurations
        vectors = self._get_vector_search_vectors(
            vector_search_term, query_vector, specific_vector_id
        )

        if not vectors:
            return 0 if count else self.browse([])

        # Generate embeddings if needed
        model_vector_map = {}
        if vector_search_term and not query_vector:
            model_vector_map, vectors = self._generate_embeddings_for_vectors(
                vectors, vector_search_term
            )

            # If no embeddings generated (no models or all failed), fallback
            if not model_vector_map or not vectors:
                if count:
                    return super().search_count(search_args)
                return super().search(
                    search_args,
                    offset=offset,
                    limit=limit,
                    order=order,
                    **kwargs,
                )

        return self._vector_search_aggregate(
            vectors=vectors,
            query_vector=query_vector,
            vector_search_term=vector_search_term,
            model_vector_map=model_vector_map,
            search_args=search_args,
            min_similarity=kwargs.get(
                "query_min_similarity",
                self.env.context.get("search_min_similarity", 0.5),
            ),
            query_operator=kwargs.get(
                "query_operator", self.env.context.get("search_vector_operator", "<=>")
            ),
            offset=offset,
            limit=limit,
            count=count,
        )

    def _vector_search_aggregate(
        self,
        vectors,
        query_vector,
        vector_search_term,
        model_vector_map,
        search_args,
        min_similarity,
        query_operator,
        offset,
        limit,
        count,
    ):
        """Performs vector search across vector configurations, aggregates,
        sorts, and limits. Chunk text comes back from each hit's payload
        (it is never stored in Odoo) and is stashed in context so the
        ``content`` field can surface it on the returned recordset."""
        # List of tuples: (score, chunk_id, text)
        aggregated_results = []

        for vector in vectors:
            current_query_vector = query_vector
            if not current_query_vector and vector_search_term:
                current_query_vector = model_vector_map.get(vector.embedding_model_id.id)

            if not current_query_vector or not vector.store_id:
                continue

            try:
                results = vector.search_vectors(
                    query_vector=current_query_vector,
                    limit=limit,
                    filter=search_args if search_args else None,
                    query_operator=query_operator,
                    min_similarity=min_similarity,
                    offset=0,
                )
                for result in results:
                    score = result.get("score", 0.0)
                    chunk_id = result.get("id")
                    payload = result.get("payload") or result.get("metadata") or {}
                    text = payload.get("text", "")
                    aggregated_results.append((score, chunk_id, text))
            except Exception as e:
                _logger.error(f"Error searching vector configuration {vector.name}: {e}")
                continue

        if not aggregated_results:
            return 0 if count else self.browse([])

        aggregated_results.sort(key=lambda x: (x[0], -x[1]), reverse=True)

        if count:
            return len(aggregated_results)

        final_results = aggregated_results[offset : offset + limit if limit else None]
        chunk_ids = [res[1] for res in final_results]
        similarities = [res[0] for res in final_results]
        chunk_texts = [res[2] for res in final_results]
        similarity_scores = dict(zip(chunk_ids, similarities))  # noqa: B905
        text_by_chunk = dict(zip(chunk_ids, chunk_texts))  # noqa: B905
        return self.browse(chunk_ids).with_context(
            similarity_scores=similarity_scores, chunk_texts=text_by_chunk
        )

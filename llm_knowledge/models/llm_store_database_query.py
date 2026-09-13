"""Declarative query interfaces exposed by a logical vector database."""

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class LLMStoreDatabaseQuery(models.Model):
    """One provider-neutral retrieval strategy for a logical vector database."""

    _name = "llm.store.database.query"
    _description = "LLM Store Database Query Interface"
    _order = "database_id, sequence, id"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    is_default = fields.Boolean(default=False, copy=False)
    database_id = fields.Many2one(
        "llm.store.database",
        required=True,
        ondelete="cascade",
        index=True,
    )
    query_mode = fields.Selection(
        [
            ("bm25", "BM25 / Full Text"),
            ("dense", "Dense Vector"),
            ("sparse", "Sparse Vector"),
            ("hybrid", "Hybrid"),
        ],
        required=True,
        default="dense",
        index=True,
    )
    hybrid_bm25 = fields.Boolean(
        string="Use BM25",
        help="Include the provider's lexical/BM25 result channel.",
    )
    hybrid_dense = fields.Boolean(
        string="Use Dense Vector",
        help="Include the configured dense embedding result channel.",
    )
    hybrid_sparse = fields.Boolean(
        string="Use Sparse Vector",
        help="Include the configured sparse embedding result channel.",
    )
    fusion_execution = fields.Selection(
        [("provider", "Vector Database"), ("client", "Client / Odoo")],
        required=True,
        default="provider",
        help="Where hybrid result fusion is performed. Client/Odoo execution is "
        "declarative until a client fusion engine is configured.",
    )
    fusion_method = fields.Selection(
        [
            ("none", "None"),
            ("rrf", "Reciprocal Rank Fusion"),
            ("weighted", "Weighted Score"),
        ],
        required=True,
        default="none",
    )
    bm25_weight = fields.Float(default=1.0)
    dense_weight = fields.Float(default=1.0)
    sparse_weight = fields.Float(default=1.0)
    rerank_execution = fields.Selection(
        [
            ("none", "No Reranking"),
            ("provider", "Vector Database"),
            ("client", "Client / Odoo"),
        ],
        required=True,
        default="none",
    )
    rerank_model_id = fields.Many2one(
        "llm.model",
        string="Client Rerank Model",
        ondelete="restrict",
        domain="[('model_use', '=', 'rerank')]",
        help="Rerank model used only when reranking executes in Odoo/client code.",
    )
    settings = fields.Json(
        default=dict,
        help="Non-secret provider-specific query parameters.",
    )

    _unique_name_per_database = models.Constraint(
        "UNIQUE(database_id, name)",
        "Query interface names must be unique per vector database.",
    )

    def _hybrid_channels(self):
        self.ensure_one()
        return {
            "bm25": self.hybrid_bm25,
            "dense": self.hybrid_dense,
            "sparse": self.hybrid_sparse,
        }

    @api.constrains(
        "database_id",
        "query_mode",
        "hybrid_bm25",
        "hybrid_dense",
        "hybrid_sparse",
        "fusion_method",
        "bm25_weight",
        "dense_weight",
        "sparse_weight",
        "rerank_execution",
        "rerank_model_id",
        "active",
        "is_default",
    )
    def _check_configuration(self):
        for query in self:
            database = query.database_id
            if query.query_mode == "dense" and not database.dense_embedding_model_id:
                raise ValidationError(
                    _("Query '%s' requires a dense embedding model.", query.name)
                )
            if query.query_mode == "sparse" and not database.sparse_embedding_model_id:
                raise ValidationError(
                    _("Query '%s' requires a sparse embedding model.", query.name)
                )

            channels = query._hybrid_channels()
            selected = [name for name, enabled in channels.items() if enabled]
            if query.query_mode == "hybrid":
                if len(selected) < 2:
                    raise ValidationError(
                        _("A hybrid query must select at least two result channels.")
                    )
                if channels["dense"] and not database.dense_embedding_model_id:
                    raise ValidationError(
                        _("The hybrid dense channel requires a dense embedding model.")
                    )
                if channels["sparse"] and not database.sparse_embedding_model_id:
                    raise ValidationError(
                        _("The hybrid sparse channel requires a sparse embedding model.")
                    )
                if query.fusion_method == "none":
                    raise ValidationError(_("A hybrid query must define a fusion method."))
            elif selected:
                raise ValidationError(
                    _("Hybrid result channels apply only to hybrid queries.")
                )
            elif query.fusion_method != "none":
                raise ValidationError(
                    _("Fusion methods apply only to hybrid queries.")
                )

            weights = {
                "bm25": query.bm25_weight,
                "dense": query.dense_weight,
                "sparse": query.sparse_weight,
            }
            if any(weight < 0 for weight in weights.values()):
                raise ValidationError(_("Query channel weights cannot be negative."))
            if query.query_mode == "hybrid" and query.fusion_method == "weighted":
                if not any(weights[channel] > 0 for channel in selected):
                    raise ValidationError(
                        _("Weighted fusion requires a positive selected-channel weight.")
                    )

            if query.rerank_execution == "client":
                if not query.rerank_model_id:
                    raise ValidationError(
                        _("Client-side reranking requires a rerank model.")
                    )
                if query.rerank_model_id.model_use != "rerank":
                    raise ValidationError(_("The client rerank model must be a reranker."))
            elif query.rerank_model_id:
                raise ValidationError(
                    _("A client rerank model is valid only for client-side reranking.")
                )

            if query.is_default:
                if not query.active:
                    raise ValidationError(_("The default query interface must be active."))
                duplicate = self.search_count(
                    [
                        ("database_id", "=", database.id),
                        ("is_default", "=", True),
                        ("id", "!=", query.id),
                    ]
                )
                if duplicate:
                    raise ValidationError(
                        _("A vector database can have only one default query interface.")
                    )

    def copy_data(self, default=None):
        return super().copy_data(default=dict(default or {}, is_default=False))

    def search_database(
        self, query_text=None, query_vector=None, limit=10, filter=None, **kwargs
    ):
        """Run this interface through Odoo's provider-neutral database API."""
        self.ensure_one()
        if not self.active:
            raise UserError(_("The selected query interface is archived."))
        if self.query_mode == "hybrid" and self.fusion_execution == "client":
            raise UserError(
                _(
                    "Client-side fusion is declarative but has no Odoo fusion engine "
                    "configured. Use provider execution or an external client."
                )
            )
        if self.rerank_execution == "client":
            raise UserError(
                _(
                    "Client-side reranking is declarative but has no Odoo rerank "
                    "executor configured. Use provider execution or an external client."
                )
            )

        dense_enabled = self.query_mode == "dense" or (
            self.query_mode == "hybrid" and self.hybrid_dense
        )
        sparse_enabled = self.query_mode == "sparse" or (
            self.query_mode == "hybrid" and self.hybrid_sparse
        )
        dense_vector = query_vector
        if query_text and dense_vector is None and dense_enabled:
            embedded = self.database_id.dense_embedding_model_id.embedding([query_text])
            dense_vector = embedded[0] if embedded else None
        sparse_vector = kwargs.pop("sparse_query_vector", None)
        if query_text and sparse_vector is None and sparse_enabled:
            embedded = self.database_id.sparse_embedding_model_id.embedding([query_text])
            sparse_vector = embedded[0] if embedded else None

        bm25_enabled = self.query_mode == "bm25" or (
            self.query_mode == "hybrid" and self.hybrid_bm25
        )
        if bm25_enabled and not query_text:
            raise UserError(_("BM25 retrieval requires query text."))
        if dense_enabled and dense_vector is None:
            raise UserError(_("Dense retrieval requires a dense query vector."))
        if sparse_enabled and sparse_vector is None:
            raise UserError(_("Sparse retrieval requires a sparse query vector."))
        if sparse_vector is not None:
            self.database_id._validate_sparse_vectors([sparse_vector])

        options = dict(self.settings or {})
        options.update(kwargs)
        options.update(
            {
                "query_text": query_text,
                "sparse_query_vector": sparse_vector,
                "query_mode": self.query_mode,
                "hybrid_channels": self._hybrid_channels(),
                "fusion_execution": self.fusion_execution,
                "fusion_method": self.fusion_method,
                "bm25_weight": self.bm25_weight,
                "dense_weight": self.dense_weight,
                "sparse_weight": self.sparse_weight,
                "rerank_execution": self.rerank_execution,
                "rerank_model_id": self.rerank_model_id.id or None,
                "query_interface_id": self.id,
            }
        )
        return self.database_id.search_vectors(
            dense_vector,
            limit=limit,
            filter=filter,
            **options,
        )

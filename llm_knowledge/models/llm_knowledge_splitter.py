"""Splitter backend model.

Polymorphic host for chunking implementations: ``splitter_type`` maps to a
component ``usage`` in the ``llm.knowledge.splitter`` collection. Sizing is
configured on the splitter record (``chunk_size``, ``chunk_overlap``).

"Different embedding methods" (raw title+content vs. contextual-retrieval
wrapping) are modeled here as just another splitter implementation
(``splitter_type='contextual'``) rather than a special-cased field
elsewhere: a splitter's job is to turn a document's markdown into the list
of strings that will actually be embedded, and wrapping each piece with
surrounding context before embedding is squarely a chunking concern.
"""

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class LLMKnowledgeSplitter(models.Model):
    _name = "llm.knowledge.splitter"
    _description = "LLM Knowledge Splitter"
    _inherit = ["collection.base"]
    _backend_name = "llm_knowledge_splitter"

    name = fields.Char(required=True)
    splitter_type = fields.Selection(
        selection=[
            ("recursive", "Recursive"),
            ("token", "Token"),
            ("contextual", "Contextual"),
        ],
        required=True,
        default="recursive",
    )
    active = fields.Boolean(default=True)
    chunk_size = fields.Integer(
        default=500,
        required=True,
        help="Target size of each chunk (in characters or tokens, depending "
        "on the splitter type).",
    )
    chunk_overlap = fields.Integer(
        default=50,
        required=True,
        help="Number of characters/tokens shared between consecutive chunks.",
    )
    context_model_id = fields.Many2one(
        "llm.model",
        string="Context Model",
        domain="[('model_use', '=', 'chat')]",
        ondelete="restrict",
        help="Required only for contextual splitting. Generates the context prefix "
        "stored as part of each chunk's text.",
    )
    chunkset_ids = fields.One2many(
        "llm.knowledge.chunkset",
        "splitter_id",
        string="Chunksets",
        readonly=True,
    )

    @api.constrains(
        "splitter_type", "chunk_size", "chunk_overlap", "context_model_id"
    )
    def _check_splitter_configuration(self):
        for splitter in self:
            if splitter.chunk_size <= 0:
                raise ValidationError(_("Chunk size must be a positive integer."))
            if splitter.chunk_overlap < 0 or splitter.chunk_overlap >= splitter.chunk_size:
                raise ValidationError(
                    _("Chunk overlap must be non-negative and smaller than chunk size.")
                )
            if splitter.splitter_type == "contextual":
                if not splitter.context_model_id:
                    raise ValidationError(_("Contextual splitting requires a context model."))
                if splitter.context_model_id.model_use != "chat":
                    raise ValidationError(_("The context model must be a chat model."))
            elif splitter.context_model_id:
                raise ValidationError(
                    _("A context model is valid only for contextual splitting.")
                )

    def write(self, vals):
        method_fields = {
            "splitter_type",
            "chunk_size",
            "chunk_overlap",
            "context_model_id",
        }
        changed = bool(method_fields.intersection(vals))
        chunksets = (
            self.mapped("chunkset_ids")
            if changed
            else self.env["llm.knowledge.chunkset"]
        )
        if chunksets:
            chunksets.mapped("database_ids").filtered(
                lambda database: database.state == "ready"
            ).write({"state": "maintenance"})
            chunksets.mapped("chunk_ids").unlink()
        result = super().write(vals)
        if chunksets:
            chunksets.write({"state": "draft"})
            chunksets.mapped("vector_ids").write({"state": "draft"})
            for collection in chunksets.mapped("collection_id"):
                collection._reset_ready_documents()
        return result

    def _get_adapter(self):
        self.ensure_one()
        if not self.splitter_type:
            return None
        with self.work_on(self._name) as work:
            return work.component(usage=self.splitter_type)

    def split(self, text, **context):
        """Split ``text`` into a list of chunk strings. ``context`` is
        forwarded to the adapter (e.g. the 'contextual' splitter uses
        ``document_record`` and the processed ``document`` contract to build
        document-level context)."""
        self.ensure_one()
        adapter = self._get_adapter()
        if adapter is None:
            return [text] if text else []
        return adapter.split(text, **context)

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

from odoo import fields, models


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
        help="Chat-capable model used by the 'contextual' splitter to "
        "generate a short situating blurb prefixed to each chunk before "
        "embedding (contextual retrieval). Unused by other splitter types.",
    )

    def _get_adapter(self):
        self.ensure_one()
        if not self.splitter_type:
            return None
        with self.work_on(self._name) as work:
            return work.component(usage=self.splitter_type)

    def split(self, text, **context):
        """Split ``text`` into a list of chunk strings. ``context`` is
        forwarded to the adapter (e.g. the 'contextual' splitter uses
        ``resource`` to build document-level context)."""
        self.ensure_one()
        adapter = self._get_adapter()
        if adapter is None:
            return [text] if text else []
        return adapter.split(text, **context)

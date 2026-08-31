from odoo import fields, models

from odoo.addons.llm.models.llm_service_dispatch import archive_dangling_service


class LLMStore(models.Model):
    _inherit = "llm.store"

    # The service itself is implemented by the ``pgvector.local.store.adapter``
    # component (``llm_knowledge_pgvector/components/``), resolved through
    # ``llm.store._get_adapter()``.
    #
    # The key is ``pgvector_local``: the bare ``pgvector`` service is a
    # *standalone* instance, provided by the ``llm_pgvector`` addon.
    service = fields.Selection(
        selection_add=[("pgvector_local", "PGVector (Odoo database)")],
        ondelete={"pgvector_local": archive_dangling_service},
    )

    # Read by the adapter when building the ANN index.
    pgvector_index_method = fields.Selection(
        [
            ("ivfflat", "IVFFlat (faster search)"),
            ("hnsw", "HNSW (balanced)"),
        ],
        string="Index Method",
        default="ivfflat",
        help="The index method to use for vector search",
    )

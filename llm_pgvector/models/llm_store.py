from odoo import fields, models

from odoo.addons.llm.models.llm_service_dispatch import archive_dangling_service


class LLMStore(models.Model):
    _inherit = "llm.store"

    # The service itself is implemented by the ``pgvector.store.adapter``
    # component (``llm_pgvector/components/``), resolved through
    # ``llm.store._get_adapter()``. Only the selection entry belongs here.
    #
    # Note the key: ``pgvector`` is the *external* instance. Embeddings kept
    # inside Odoo's own database are the ``pgvector_local`` service, provided by
    # ``llm_knowledge_pgvector``.
    service = fields.Selection(
        selection_add=[("pgvector", "PgVector (external)")],
        ondelete={"pgvector": archive_dangling_service},
    )

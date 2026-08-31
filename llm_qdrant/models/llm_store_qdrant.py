from odoo import fields, models

from odoo.addons.llm.models.llm_service_dispatch import archive_dangling_service


class LLMStore(models.Model):
    _inherit = "llm.store"

    # The service itself is implemented by the ``qdrant.store.adapter``
    # component (``llm_qdrant/components/``), resolved through
    # ``llm.store._get_adapter()``. Only the selection entry belongs here.
    service = fields.Selection(
        selection_add=[("qdrant", "Qdrant")],
        ondelete={"qdrant": archive_dangling_service},
    )

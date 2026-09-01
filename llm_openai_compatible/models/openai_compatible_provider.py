from odoo import fields, models

from odoo.addons.llm.models.llm_service_dispatch import archive_dangling_service


class LLMProvider(models.Model):
    _inherit = "llm.provider"

    # The service itself is implemented by the ``openai_compatible.provider.adapter``
    # component (``llm_openai_compatible/components/``), resolved through
    # ``llm.provider._get_adapter()``. Only the selection entry belongs here.
    service = fields.Selection(
        selection_add=[("openai_compatible", "OpenAI Compatible")],
        ondelete={"openai_compatible": archive_dangling_service},
    )

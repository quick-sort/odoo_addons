from odoo import fields, models

from odoo.addons.llm.models.llm_service_dispatch import archive_dangling_service


class LLMProvider(models.Model):
    _inherit = "llm.provider"

    # The service itself is implemented by the ``anthropic.provider.adapter``
    # component (``llm_anthropic/components/``), resolved through
    # ``llm.provider._get_adapter()``. Only the selection entry belongs here.
    service = fields.Selection(
        selection_add=[("anthropic", "Anthropic")],
        ondelete={"anthropic": archive_dangling_service},
    )

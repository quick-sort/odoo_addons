"""Service values used by the configuration-only knowledge demo records."""

from odoo import fields, models

from odoo.addons.llm.models.llm_service_dispatch import archive_dangling_service

DEMO_SERVICE = "knowledge_demo"
DEMO_SERVICE_LABEL = "Knowledge Configuration Demo (No Runtime Adapter)"


class LLMProviderKnowledgeDemo(models.Model):
    _inherit = "llm.provider"

    service = fields.Selection(
        selection_add=[(DEMO_SERVICE, DEMO_SERVICE_LABEL)],
        ondelete={DEMO_SERVICE: archive_dangling_service},
    )


class LLMStoreKnowledgeDemo(models.Model):
    _inherit = "llm.store"

    service = fields.Selection(
        selection_add=[(DEMO_SERVICE, DEMO_SERVICE_LABEL)],
        ondelete={DEMO_SERVICE: archive_dangling_service},
    )

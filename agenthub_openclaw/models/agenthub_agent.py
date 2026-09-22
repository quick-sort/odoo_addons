from odoo import fields, models


class AgenthubAgent(models.Model):
    """OpenClaw reply semantics configuration for ``agenthub.agent``."""

    _inherit = "agenthub.agent"

    agent_type = fields.Selection(
        selection_add=[("openclaw", "OpenClaw")],
        ondelete={"openclaw": "cascade"},
    )

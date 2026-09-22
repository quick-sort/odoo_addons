"""OpenClaw reply adapter for ``agenthub.agent``."""

from odoo.tools import html2plaintext

from odoo.addons.component.core import Component

from ..services.semantics import strip_think


class AgenthubAgentOpenclaw(Component):
    _name = "agenthub.agent.openclaw"
    _inherit = "agenthub.agent.adapter"
    _usage = "openclaw"

    def reply(self, agent, message):
        """Return the visible reply text, with ``<think>`` blocks removed."""
        text = message.agenthub_content or html2plaintext(message.body or "")
        visible, _think = strip_think(text)
        return visible

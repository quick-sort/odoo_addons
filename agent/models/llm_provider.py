# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

"""Bridge ``llm.provider`` into the component system.

Turns the existing provider model into a ``collection.base`` so components can
subscribe to it (``_collection = "llm.provider"``) and resolve per-service
adapters. A generic fallback delegates to the provider's own methods, so every
provider shipped by ``odoo-llm`` keeps working without modification.
"""

from odoo import models

from odoo.addons.component.exception import NoComponentError


class LLMProvider(models.Model):
    _name = "llm.provider"
    _inherit = ["llm.provider", "collection.base"]

    def _get_agent_adapter(self):
        """Return the ``agent.provider.adapter`` component for this provider.

        Uses the component registered for ``self.service`` (e.g. ``openai``)
        when one exists, otherwise falls back to the generic adapter that
        delegates to the provider's own ``chat``/``embedding`` methods.
        """
        self.ensure_one()
        with self.work_on("llm.provider") as work:
            try:
                return work.component(usage=self.service)
            except NoComponentError:
                return work.component_by_name("agent.provider.adapter.generic")

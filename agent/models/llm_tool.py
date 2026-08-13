# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

"""Bridge ``llm.tool`` into the component system.

Same pattern as ``llm.provider``: the tool model becomes a ``collection.base``
and its ``implementation`` selection maps onto an ``agent.tool.executor``
component. A generic fallback delegates to ``tool.execute()`` (which already
dispatches to ``{implementation}_execute``), so existing tools keep working.
"""

from odoo import models

from odoo.addons.component.exception import NoComponentError


class LLMTool(models.Model):
    _name = "llm.tool"
    _inherit = ["llm.tool", "collection.base"]

    def _get_tool_executor(self):
        """Return the ``agent.tool.executor`` component for this tool.

        Uses the component registered for ``self.implementation`` when one
        exists, otherwise falls back to the generic executor.
        """
        self.ensure_one()
        with self.work_on("llm.tool") as work:
            try:
                return work.component(usage=self.implementation)
            except NoComponentError:
                return work.component_by_name("agent.tool.executor.generic")

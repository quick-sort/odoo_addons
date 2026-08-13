# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

"""Tool executor components.

Polymorphic seam that replaces ``odoo-llm``'s ``{implementation}_execute``
dispatch. The abstract component lives in the ``llm.tool`` collection; a
concrete executor registers a ``_usage`` equal to the tool's ``implementation``
(function, invoke_assistant, mcp, ...). A generic fallback delegates to
``tool.execute()`` (which already dispatches to ``{implementation}_execute``),
so every existing tool keeps working.
"""

from odoo.addons.component.core import AbstractComponent, Component


class AgentToolExecutor(AbstractComponent):
    _name = "agent.tool.executor"
    _collection = "llm.tool"

    def execute(self, tool, parameters, session=None):
        """Execute one tool call and return a JSON-serializable result.

        ``tool`` is the ``llm.tool`` record, ``parameters`` the already-parsed
        arguments dict, ``session`` the ``llm.thread`` (or ``None``).
        """
        raise NotImplementedError


class GenericToolExecutor(Component):
    _name = "agent.tool.executor.generic"
    _inherit = "agent.tool.executor"
    # No ``_usage``: only reached by name as a fallback when no
    # implementation-specific executor is registered.
    _usage = None

    def execute(self, tool, parameters, session=None):
        return tool.execute(parameters)

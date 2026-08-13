# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

"""Provider adapter components.

Polymorphic seam that replaces ``odoo-llm``'s ``{service}_{verb}`` string
dispatch. The abstract component lives in the ``llm.provider`` collection; a
concrete adapter registers a ``_usage`` equal to the provider's ``service``
(openai, anthropic, ...). A generic fallback delegates to the provider's own
methods, so all existing providers work unchanged.
"""

from odoo.addons.component.core import AbstractComponent, Component


class AgentProviderAdapter(AbstractComponent):
    _name = "agent.provider.adapter"
    _collection = "llm.provider"

    def chat(
        self,
        model,
        messages,
        tools=None,
        stream=False,
        prepend_messages=None,
        **kwargs,
    ):
        """Call the chat endpoint.

        ``messages`` is a ``mail.message`` recordset, ``tools`` an ``llm.tool``
        recordset, ``prepend_messages`` a list of ``{"role", "content"}`` dicts.

        Returns the standard dict ``{"content", "tool_calls", "images",
        "thinking", "error"}``, or a generator of such dicts when ``stream``.
        """
        raise NotImplementedError

    def embedding(self, texts, model):
        """Return a list of vectors for ``texts``."""
        raise NotImplementedError

    def format_tools(self, tools):
        """Format an ``llm.tool`` recordset in provider-native form."""
        raise NotImplementedError

    def validate_config(self):
        """Optional connectivity self-test. Raise on failure."""


class GenericProviderAdapter(Component):
    _name = "agent.provider.adapter.generic"
    _inherit = "agent.provider.adapter"
    # No ``_usage``: never returned by a usage lookup, only reached by name as
    # a fallback when no service-specific adapter is registered.
    _usage = None

    def chat(
        self,
        model,
        messages,
        tools=None,
        stream=False,
        prepend_messages=None,
        **kwargs,
    ):
        return self.collection.chat(
            messages,
            model=model,
            tools=tools,
            stream=stream,
            prepend_messages=prepend_messages,
            **kwargs,
        )

    def embedding(self, texts, model):
        return self.collection.embedding(texts, model=model)

    def format_tools(self, tools):
        return self.collection.format_tools(tools)

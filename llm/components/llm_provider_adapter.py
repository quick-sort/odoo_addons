"""Base component for LLM provider service adapters.

One adapter per service (``openai``, ``anthropic``, ...), selected by
``llm.provider._get_adapter()`` through the component ``_usage``, which must
equal the value stored in ``llm.provider.service``.

A concrete adapter looks like::

    from odoo.addons.component.core import Component

    class OpenAIProviderAdapter(Component):
        _name = "openai.provider.adapter"
        _inherit = "llm.provider.adapter"      # inherits _collection
        _usage = "openai"                      # == llm.provider.service

        def chat(self, provider, messages, model=None, stream=False,
                 tools=None, prepend_messages=None, **kwargs):
            ...

Every method receives the ``llm.provider`` record as its first positional
argument. Reading configuration through that argument rather than through
``self.collection`` keeps adapters usable from plain unit tests, which can
instantiate them with ``object.__new__(OpenAIProviderAdapter)`` and pass a
mock provider -- no database and no component registry needed.
"""

from odoo.addons.component.core import AbstractComponent


class LLMProviderAdapter(AbstractComponent):
    """Service adapter contract for ``llm.provider``.

    Every contract below is mandatory and declared as a stub, so signatures are
    documented where they are implemented and a misspelled override surfaces as
    an unimplemented method rather than at call time.

    This adapter has no optional contracts. Two methods that used to be
    dispatched here no longer are:

    - ``test_model`` -- connectivity testing is routed purely on
      ``model.model_use`` (see ``llm.provider.test_model``), never on the
      adapter. A service needing a different probe for one usage overrides
      the matching ``_test_<usage>_model`` model method directly (``_inherit``
      + ``super()``), not this component.
    - ``determine_model_use`` -- no adapter ever implemented it; it is a plain
      model method now, overridden the same way.
    """

    _name = "llm.provider.adapter"
    # Scope the lookup to llm.provider. Without it the component would be
    # returned for every collection in the database (see
    # ComponentRegistry.lookup: a component with no _collection matches all).
    _collection = "llm.provider"

    def _not_implemented(self, method):
        raise NotImplementedError(
            f"Provider adapter '{self._usage}' ({self._name}) does not "
            f"implement {method}()"
        )

    def get_client(self, provider):
        """Return the configured SDK client for ``provider``."""
        return self._not_implemented("get_client")

    def normalize_prepend_messages(self, provider, prepend_messages):
        """Adapt pre-formatted messages (system prompts, ...) to the service payload shape."""
        return self._not_implemented("normalize_prepend_messages")

    def chat(
        self,
        provider,
        messages,
        model=None,
        stream=False,
        tools=None,
        prepend_messages=None,
        **kwargs,
    ):
        """Return a ``dict`` with ``content`` / ``tool_calls`` / ``images``.

        When ``stream`` is true, return a generator yielding such dicts.
        """
        return self._not_implemented("chat")

    def embedding(self, provider, texts, model=None):
        """Return one vector per input text."""
        return self._not_implemented("embedding")

    def generate(self, provider, input_data, model=None, stream=False, **kwargs):
        """Return an ``(output, urls)`` tuple for binary generation."""
        return self._not_implemented("generate")

    def models(self, provider, model_id=None):
        """Yield ``{"name": str, "details": dict}`` for the available models."""
        return self._not_implemented("models")

    def format_tools(self, provider, tool_records):
        """Convert an ``llm.tool`` recordset to the service tool payload."""
        return self._not_implemented("format_tools")

    def format_messages(self, provider, messages, system_prompt=None, model=None):
        """Convert a ``mail.message`` recordset to the service message payload."""
        return self._not_implemented("format_messages")

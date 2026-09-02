"""Base component for ``llm.tool`` executors.

One executor per way of running a tool (``model_method``, ``server_action``,
``mcp``, ...), selected by ``llm.tool._dispatch()`` through the component
``_usage``, which must equal the value stored in ``llm.tool.executor``.

A concrete executor looks like::

    from odoo.addons.component.core import Component

    class ModelMethodToolExecutor(Component):
        _name = "model_method.tool.executor"
        _inherit = "llm.tool.executor"
        _usage = "model_method"

        def execute(self, params):
            tool = self.collection
            ...

        def validate(self, tool):
            if not (tool.res_model and tool.res_method):
                raise ValidationError(...)

Unlike ``llm.provider.adapter`` / ``llm.store.adapter``, executors do **not**
receive the ``llm.tool`` record as a leading positional argument
(``llm.tool._dispatch_pass_record = False``): an adapter method's signature is
itself the JSON Schema advertised to the LLM, and an extra leading parameter
would show up as a tool argument. Executors read the record from
``self.collection`` instead.
"""

from odoo.addons.component.core import AbstractComponent


class LLMToolExecutor(AbstractComponent):
    """Executor contract for ``llm.tool``.

    ``execute`` is mandatory and declared below as a stub, so a misspelled
    override surfaces as an unimplemented method rather than at call time.

    ``validate`` is optional -- declaring a stub here would make ``hasattr``
    true for every executor and ``llm.tool._check_executor_configuration``
    would never fall through to "nothing to validate". It is documented here
    instead:

    ``validate(tool)``
        Raise :exc:`odoo.exceptions.ValidationError` if ``tool`` is not
        correctly configured for this executor (e.g. a ``model_method``
        executor needs both ``res_model`` and ``res_method``). Called from
        ``llm.tool._check_executor_configuration``, itself an
        ``@api.constrains`` hook, so it runs on every create/write touching
        the watched fields.
    """

    _name = "llm.tool.executor"
    # Scope the lookup to llm.tool. Without it the component would be
    # returned for every collection in the database (see
    # ComponentRegistry.lookup: a component with no _collection matches all).
    _collection = "llm.tool"

    def _not_implemented(self, method):
        raise NotImplementedError(
            f"Tool executor '{self._usage}' ({self._name}) does not "
            f"implement {method}()"
        )

    def execute(self, params):
        """Run the tool with the validated ``params`` dict. Return the result."""
        return self._not_implemented("execute")

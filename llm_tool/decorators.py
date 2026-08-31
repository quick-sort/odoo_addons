"""The ``@llm_tool`` decorator: expose a model method to an LLM.

Decorating is *passive* -- it only tags the function object. The startup scan in
``llm.tool._scan_tool_decorators`` walks ``env.registry`` looking for those tags
and registers one ``llm.tool`` row per decorated method, with
``executor='model_method'`` and ``source='code'``.

Because the row's metadata is derived rather than typed in, the decorator is
strict about what it needs: **type hints on every parameter, a return
annotation, and a docstring**. All three are errors, not warnings -- a tool the
LLM cannot understand is worse than no tool.
"""

import inspect
import logging
from functools import wraps

_logger = logging.getLogger(__name__)

#: Attributes the scan reads back off the decorated function.
_TOOL_ATTRS = (
    "_is_llm_tool",
    "_llm_tool_name",
    "_llm_tool_description",
    "_llm_tool_metadata",
)


def llm_tool(func=None, *, name=None, description=None, schema=None, **metadata):
    """Mark a model method as an LLM tool.

    Everything the registry needs comes from the method itself:

    - **name** -- the function name, or the ``name`` argument
    - **description** -- the docstring, or the ``description`` argument
    - **input_schema** -- the type hints, or the ``schema`` argument

    Usage::

        class SaleOrder(models.Model):
            _inherit = "sale.order"

            @llm_tool
            def create_sales_quote(
                self, customer_name: str, products: list[str]
            ) -> dict:
                \"\"\"Create a sales quotation for a customer.\"\"\"
                return {"quote_id": 123}

    Annotations the LLM client may use are passed through as metadata::

        @llm_tool(read_only_hint=True, destructive_hint=False)
        def odoo_record_retriever(self, model: str) -> dict:
            \"\"\"Read records from any model.\"\"\"

    For a legacy method without annotations, supply the schema explicitly::

        @llm_tool(schema={
            "type": "object",
            "properties": {"partner_id": {"type": "integer"}},
            "required": ["partner_id"],
        })
        def create_invoice(self, partner_id, amount):
            \"\"\"Create an invoice for a partner.\"\"\"

    Args:
        func: the function, when used as ``@llm_tool`` without parentheses
        name: tool name override (defaults to the function name)
        description: description override (defaults to the docstring)
        schema: explicit JSON Schema, for methods without type hints
        **metadata: passed through to the row -- ``title``, ``read_only_hint``,
            ``idempotent_hint``, ``destructive_hint``, ``open_world_hint``

    Raises:
        ValueError: if the docstring is missing, or (without an explicit
            ``schema``) if any parameter or the return value lacks a type hint

    Note:
        There is no ``xml_managed`` flag any more. To hand-manage a tool, create
        the ``llm.tool`` row with ``source='manual'`` -- the scan then ignores
        it. ``action_duplicate_as_manual`` does that from an existing row.
    """

    def decorator(f):
        tool_name = name or f.__name__
        tool_description = description or inspect.getdoc(f)

        if not tool_description or not tool_description.strip():
            raise ValueError(
                f"@llm_tool requires a docstring.\n"
                f"Tool '{tool_name}' has none, so the LLM would receive an empty "
                f"description.\n\n"
                f"Fix: add a docstring to {f.__name__}(), or pass "
                f"description='...' to the decorator."
            )

        if schema:
            f._llm_tool_schema = schema
        else:
            _validate_type_hints(f, tool_name)

        f._is_llm_tool = True
        f._llm_tool_name = tool_name
        f._llm_tool_description = tool_description
        f._llm_tool_metadata = metadata

        @wraps(f)
        def wrapper(*args, **kwargs):
            return f(*args, **kwargs)

        # functools.wraps copies __doc__ and __annotations__ and sets
        # __wrapped__, so inspect.signature() on the bound wrapper still yields
        # the real signature. Copy the tool tags across explicitly.
        for attr in _TOOL_ATTRS:
            setattr(wrapper, attr, getattr(f, attr))
        if hasattr(f, "_llm_tool_schema"):
            wrapper._llm_tool_schema = f._llm_tool_schema

        return wrapper

    # Support both @llm_tool and @llm_tool(...)
    return decorator if func is None else decorator(func)


def _validate_type_hints(func, tool_name):
    """Require a hint on every parameter and on the return value.

    The signature *is* the tool's JSON Schema, so a missing hint means a
    parameter the LLM cannot be told about.
    """
    sig = inspect.signature(func)

    for param_name, param in sig.parameters.items():
        if param_name == "self":
            continue
        if param.annotation is inspect.Parameter.empty:
            raise ValueError(
                f"@llm_tool requires type hints.\n"
                f"Tool '{tool_name}' parameter '{param_name}' has none.\n\n"
                f"Fix: annotate it, e.g.\n"
                f"  def {func.__name__}(self, {param_name}: str, ...) -> dict:\n\n"
                f"Or provide an explicit schema:\n"
                f"  @llm_tool(schema={{...}})\n"
                f"  def {func.__name__}(self, {param_name}, ...):"
            )

    if sig.return_annotation is inspect.Signature.empty:
        raise ValueError(
            f"@llm_tool requires a return type hint.\n"
            f"Tool '{tool_name}' has none.\n\n"
            f"Fix: annotate the return value, e.g.\n"
            f"  def {func.__name__}(...) -> dict:"
        )


def is_llm_tool(func):
    """Return whether ``func`` is decorated with :func:`llm_tool`."""
    return getattr(func, "_is_llm_tool", False)


def get_tool_metadata(func):
    """Return the decorator metadata of ``func``, or ``None`` if undecorated."""
    if not is_llm_tool(func):
        return None

    return {
        "name": getattr(func, "_llm_tool_name", None),
        "description": getattr(func, "_llm_tool_description", None),
        "metadata": getattr(func, "_llm_tool_metadata", {}),
        "schema": getattr(func, "_llm_tool_schema", None),
    }

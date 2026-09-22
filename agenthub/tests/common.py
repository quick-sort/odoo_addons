"""Shared test helpers for the agenthub suite."""

from contextlib import contextmanager


@contextmanager
def selection_value(model, field_name, value, label="Test Value"):
    """Temporarily add ``value`` to a static Selection field.

    ``channel_type`` / ``agent_type`` are validated on write against the field's
    ``_selection`` dict, so a type no installed addon contributes cannot simply
    be passed to ``create()`` in a test. Both attributes move together:
    ``get_values`` reads ``field.selection`` while ``convert_to_cache`` checks
    ``field._selection``.

    Mirrors ``infohub/tests/common.py``.
    """
    field = type(model)._fields[field_name]
    original_selection = field.selection
    original_lookup = field._selection

    field.selection = list(original_selection) + [(value, label)]
    field._selection = dict(original_lookup or {}, **{value: label})
    try:
        yield
    finally:
        field.selection = original_selection
        field._selection = original_lookup

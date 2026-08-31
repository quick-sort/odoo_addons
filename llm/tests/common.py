"""Shared test helpers for the LLM service-dispatch stack."""

from contextlib import contextmanager


@contextmanager
def selection_value(model, field_name, value, label="Test Value"):
    """Temporarily add ``value`` to a static Selection field.

    Tests used to inject a fake service by patching ``_get_available_services``,
    which the field's ``selection=lambda`` consulted on every read. These fields
    are now static lists extended with ``selection_add``, so the values are
    fixed at registry build *and* validated on write -- patching a model method
    no longer has any effect, and creating a record with an unknown service
    raises ``ValueError``.

    Both attributes have to move together: ``get_values`` (used by views and by
    ``_description_selection``) reads ``field.selection``, while
    ``convert_to_cache`` (used on write) checks membership in the
    ``field._selection`` dict.

    The field object is shared per registry, so this mutates process-global
    state for the duration of the block -- the same trade-off as
    ``mock.patch.object``, and safe under Odoo's single-threaded test runner.
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

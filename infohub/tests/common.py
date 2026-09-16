"""Shared helpers for the InfoHub test suite."""

from contextlib import contextmanager

from odoo.addons.component.core import Component


@contextmanager
def selection_value(model, field_name, value, label="Test Value"):
    """Temporarily add ``value`` to a static Selection field.

    ``channel_type`` is validated on write against the field's ``_selection``
    dict, so a channel type that no installed addon contributes cannot simply be
    passed to ``create()`` in a test. Both attributes have to move together:
    ``get_values`` (used by views) reads ``field.selection``, while
    ``convert_to_cache`` (used on write) checks ``field._selection``.

    The field object is shared per registry, so this mutates process-global
    state for the duration of the block — the same trade-off as
    ``mock.patch.object``, and safe under Odoo's single-threaded test runner.

    Mirrors ``llm/tests/common.py``.
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


def stub_channel_components(channel_type, items_ref):
    """Build the fetch/content components for a stand-in channel type.

    ``items_ref`` is a one-element list used as a mutable box, so the returned
    fetch component can read whatever the test puts there::

        items = []
        Fetch, Content = stub_channel_components("probe", items)
        self._build_components(Fetch, Content)
        items.append({"title": "x"})

    Components are returned, not registered — the caller registers them with
    ``self._build_components`` from ``ComponentRegistryCase``, which puts them
    in the test's isolated registry instead of the database-wide one.
    """

    class StubFetch(Component):
        _name = f"infohub.fetch.{channel_type}"
        _inherit = "infohub.fetch"
        _usage = f"infohub.fetch.{channel_type}"

        def fetch_news(self, date_from=None, date_to=None, **kwargs):
            return {}, list(items_ref)

    class StubContent(Component):
        _name = f"infohub.content.{channel_type}"
        _inherit = "infohub.content"
        _usage = f"infohub.content.{channel_type}"

        def subject(self, raw_data):
            return (raw_data or {}).get("headline", "")

        def source(self, raw_data):
            return (raw_data or {}).get("publisher", "")

        def date(self, raw_data):
            return (raw_data or {}).get("published", "")

        def build_content(self, raw_data):
            return (raw_data or {}).get("body", "")

    return StubFetch, StubContent

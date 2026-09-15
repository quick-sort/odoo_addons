"""Extension points every channel implements.

A channel type ``X`` provides components named ``infohub.fetch.X`` and
``infohub.content.X``. They are resolved by usage suffix
(``WorkContext(...).component(usage=f"infohub.fetch.{channel_type}")``), so
usages stay unique by construction and no ``_component_match`` disambiguation
is needed.

Component inheritance must use the ``_inherit`` *string* — Python class
inheritance is not seen by the component registry, so the chain would silently
break. Likewise, never name a method on a component after a reserved framework
attribute (``_abstract``, ``_name``, ``_inherit``, ``_collection``, ``_usage``,
``_apply_on``, ``_register``, ``_module``): ``_abstract`` in particular is a
class attribute the framework reads as a boolean, so defining a method with that
name flips it truthy and the component is silently excluded from lookup.
"""

from odoo.addons.component.core import AbstractComponent
from odoo.tools import html2plaintext


class InfohubFetch(AbstractComponent):
    """Pull items from the channel's upstream."""

    _name = "infohub.fetch"
    _collection = "infohub.channel"

    def fetch_news(self, date_from=None, date_to=None, **kwargs):
        """Return ``(raw_response, items)``.

        ``items`` is a list of dicts::

            {"title": str, "url": str, "summary": str,
             "published_date": str, "raw_data": dict}
        """
        raise NotImplementedError(
            f"fetch_news() not implemented for channel_type="
            f"{self.collection.channel_type!r}"
        )


class InfohubContent(AbstractComponent):
    """Interpret a channel's own ``raw_data`` shape.

    Every upstream carries a different payload layout, so the concrete component
    knows how to read its own. The base provides a best-effort fallback across
    common key names plus shared helpers.
    """

    _name = "infohub.content"
    _collection = "infohub.channel"

    #: Keys commonly holding the title, in order of preference.
    TITLE_KEYS = ("subject", "title", "name", "headline")
    #: Keys commonly holding the body.
    BODY_KEYS = ("summary", "abstract", "description", "content", "body")
    #: Keys commonly holding the source name.
    SOURCE_KEYS = ("source", "publisher", "sourceName", "email_from")

    def build_content(self, raw_data):
        """Render ``raw_data`` as readable plain text."""
        data = raw_data or {}
        title = self._first(data, self.TITLE_KEYS)
        body = self._first(data, self.BODY_KEYS)
        parts = [p for p in (title, html2plaintext(body) if body else "") if p]
        return "\n\n".join(parts)

    def subject(self, raw_data):
        """The item's title."""
        return self._first(raw_data or {}, self.TITLE_KEYS)

    def date(self, raw_data):
        """The item's publication date, as a string Odoo can parse.

        Returns ``""`` when the channel's payload carries no usable date.
        """
        return ""

    def source(self, raw_data):
        """The name of the source the item came from."""
        return self._first(raw_data or {}, self.SOURCE_KEYS)

    def url(self, raw_data):
        """A link to the original item, if the payload carries one."""
        return self._first(raw_data or {}, ("link", "url", "source_url"))

    # ------------------------------------------------------------------
    # Helpers shared by concrete components
    # ------------------------------------------------------------------

    @staticmethod
    def _first(data, keys):
        """Return the first non-empty value among ``keys``, as a string."""
        for key in keys:
            value = data.get(key)
            if value:
                return str(value)
        return ""

    @staticmethod
    def _labelled(data, label_keys):
        """Build ``Label: value`` lines, joining list values with commas."""
        lines = []
        for label, key in label_keys:
            value = data.get(key)
            if not value:
                continue
            if isinstance(value, (list, tuple)):
                value = ", ".join(str(x) for x in value if x)
            if value:
                lines.append(f"{label}: {value}")
        return lines

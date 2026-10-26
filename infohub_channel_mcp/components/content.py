from datetime import datetime, timezone

from odoo.addons.component.core import Component
from odoo.tools import html2plaintext


class InfohubContentMcp(Component):
    _name = "infohub.content.mcp"
    _inherit = "infohub.content"
    _usage = "infohub.content.mcp"

    def build_content(self, raw_data):
        data = raw_data or {}
        parts = []
        header = self._labelled(
            data,
            [
                ("Title", "title"),
                ("Source", "source"),
                ("Date", "published_date"),
                ("Author", "author"),
            ],
        )
        if header:
            parts.append("\n".join(header))

        body = self._first(data, ("summary", "abstract", "content", "description", "body"))
        if body:
            parts.append(html2plaintext(body))
        return "\n\n".join(parts)

    def subject(self, raw_data):
        return self._first(
            raw_data or {}, ("title", "titleOrigin", "headline", "name")
        )

    def source(self, raw_data):
        """The publisher named by the tool, when it reports one."""
        return self._first(
            raw_data or {},
            ("source", "SOURCENAME", "sourceName", "publisher", "journal"),
        )

    def date(self, raw_data):
        """Normalise the tool's timestamp to a format the core can parse.

        MCP tools almost always answer in ISO-8601, often with a ``T``
        separator and a ``Z``/offset suffix (``2026-09-01T10:00:00Z``), while
        ``fields.Datetime.to_datetime`` only accepts ``YYYY-MM-DD[ HH:MM[:SS]]``.
        Handing the raw value over therefore raised ``ValueError`` in the core,
        which silently fell back to the fetch time — every MCP item looked as
        if it had just been published. Parse it here, where the payload shape
        is known, and return the naive UTC string the core expects.

        Values that are not ISO-8601 are returned untouched: the core still
        logs them instead of pretending they were parsed.
        """
        value = self._first(
            raw_data or {},
            ("published_date", "publishedDate", "date", "publishDate"),
        )
        if not value:
            return ""
        text = value.strip()
        # ``fromisoformat`` only learned to read "Z" in Python 3.11; keep the
        # explicit replacement so the component behaves the same on older
        # interpreters too.
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return value
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed.strftime("%Y-%m-%d %H:%M:%S")

    def url(self, raw_data):
        return self._first(
            raw_data or {}, ("url", "link", "sourceUrl", "source_url")
        )

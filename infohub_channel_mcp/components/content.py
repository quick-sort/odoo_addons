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
        return self._first(
            raw_data or {},
            ("published_date", "publishedDate", "date", "publishDate"),
        )

    def url(self, raw_data):
        return self._first(
            raw_data or {}, ("url", "link", "sourceUrl", "source_url")
        )

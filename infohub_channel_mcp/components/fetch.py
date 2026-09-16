"""Pull news from a third-party MCP tool.

The tool's reply is opaque — nothing in MCP describes its schema — so the
result is normalised defensively: a JSON document is decoded, a list is taken
as-is, and a dict is probed for a handful of common envelope keys. A tool that
renames its envelope therefore degrades to "no items" rather than raising.
"""

import json
import logging

from odoo.addons.component.core import Component
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

#: MCP's tools/call has no pagination of its own beyond what the tool exposes,
#: so these bound a misbehaving server rather than describing a real page size.
DEFAULT_PAGE_SIZE = 50
MAX_PAGES = 40
MAX_ITEMS = 1000

#: Envelope keys a tool may wrap its list in.
LIST_KEYS = ("records", "items", "data", "results", "news", "list", "entries")


class InfohubFetchMcp(Component):
    _name = "infohub.fetch.mcp"
    _inherit = "infohub.fetch"
    _usage = "infohub.fetch.mcp"

    def fetch_news(self, date_from=None, date_to=None, **kwargs):
        channel = self.collection
        if not channel.mcp_client_id:
            raise UserError(
                f"Channel {channel.display_name!r} has no MCP client configured."
            )
        if not channel.mcp_tool_name:
            raise UserError(
                f"Channel {channel.display_name!r} has no tool name configured."
            )

        arguments = self._arguments(date_from, date_to, kwargs)
        response = channel.mcp_client_id.call_tool(channel.mcp_tool_name, arguments)
        items = self._to_items(_as_document(response))
        return response, items

    def _arguments(self, date_from, date_to, extra):
        """Build the tool call arguments, omitting anything unset."""
        arguments = {}
        if date_from:
            arguments["dateFrom"] = _as_ymd(date_from)
        if date_to:
            arguments["dateTo"] = _as_ymd(date_to)
        for key, value in extra.items():
            if value not in (None, "", False):
                arguments[key] = value
        return arguments

    def _to_items(self, document):
        """Normalise a decoded tool result into a list of item dicts."""
        records = _as_items(document)
        items = []
        for record in records[:MAX_ITEMS]:
            if not isinstance(record, dict):
                continue
            items.append(
                {
                    "title": _first(record, ("title", "titleOrigin", "headline", "name")),
                    "url": _first(record, ("url", "link", "sourceUrl", "source_url")),
                    "summary": _first(record, ("summary", "abstract", "description")),
                    "published_date": _first(
                        record, ("published_date", "publishedDate", "date", "publishDate")
                    ),
                    # Keep every field the tool returned: filter_domain works on
                    # raw_data, and a tool's own keys are exactly what a channel
                    # filter would want to match on.
                    "raw_data": record,
                }
            )
        return items


def _as_ymd(value):
    """``YYYY-MM-DD`` for a date, datetime or string; ``""`` when empty."""
    if not value:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value)


def _as_document(payload):
    """Decode a tool result into whatever it contains, or ``None``.

    ``llm.mcp.client.call_tool`` wraps the tool's text content under
    ``{"result": ...}``, and that text is usually one JSON document.
    """
    if payload is None:
        return None
    if isinstance(payload, dict) and "result" in payload:
        payload = payload["result"]
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except (ValueError, TypeError):
            _logger.warning(
                "infohub mcp: tool result was not JSON, ignoring: %r", payload[:200]
            )
            return None
    return payload


def _as_items(document):
    """Normalise a decoded result into a list, accepting both shapes."""
    if document is None:
        return []
    if isinstance(document, list):
        return document
    if isinstance(document, dict):
        for key in LIST_KEYS:
            value = document.get(key)
            if isinstance(value, list):
                return value
    return []


def _first(data, keys):
    for key in keys:
        value = data.get(key)
        if value:
            return str(value)
    return ""

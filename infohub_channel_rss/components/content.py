import datetime
import logging
from email.utils import parsedate_to_datetime

from odoo.addons.component.core import Component
from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)


class InfohubContentRss(Component):
    _name = "infohub.content.rss"
    _inherit = "infohub.content"
    _usage = "infohub.content.rss"

    def build_content(self, raw_data):
        data = raw_data or {}
        parts = []
        header = self._labelled(
            data,
            [
                ("Title", "title"),
                ("Feed", "feed_title"),
                ("Author", "author"),
                ("Date", "published"),
                ("Categories", "categories"),
            ],
        )
        if header:
            parts.append("\n".join(header))

        body = self._first(data, ("content", "summary", "description"))
        if body:
            parts.append(html2plaintext(body))
        return "\n\n".join(parts)

    def subject(self, raw_data):
        return self._first(raw_data or {}, ("title",))

    def url(self, raw_data):
        return self._first(raw_data or {}, ("link", "origLink", "guid"))

    def source(self, raw_data):
        """The feed's own title, used to recognise the source.

        Falls back to the author, which for many feeds names the publication.
        """
        data = raw_data or {}
        return self._first(data, ("feed_title", "author"))

    def date(self, raw_data):
        """Publication date as a string Odoo can parse, or ``""``.

        Feeds are inconsistent here — RFC 822, ISO 8601 and free-form local
        formats all appear — so the shapes are tried in order rather than
        relying on a single parser.
        """
        value = self._first(raw_data or {}, ("published", "pubDate", "updated", "date"))
        if not value:
            return ""
        parsed = self._parse(value)
        return parsed.strftime("%Y-%m-%d %H:%M:%S") if parsed else ""

    @staticmethod
    def _parse(value):
        """Best-effort parse of a feed date string into a naive UTC datetime."""
        value = (value or "").strip()
        if not value:
            return None

        # ISO-8601 first: Atom uses it, and Python 3.11+ reads most forms.
        try:
            parsed = datetime.datetime.fromisoformat(
                value.replace("Z", "+00:00")
            )
        except ValueError:
            parsed = None

        if parsed is None:
            # RFC 822/2822 is the RSS norm, and its parser is deliberately
            # lenient where ``strptime`` is not: a time without seconds and a
            # named zone (GlobeNewswire's ``22:59 GMT``) are both accepted.
            # Without this, those dates were rejected and the core stamped the
            # item with the fetch time instead.
            try:
                parsed = parsedate_to_datetime(value)
            except (TypeError, ValueError):
                parsed = None

        if parsed is None:
            for fmt in (
                "%a, %d %b %Y %H:%M:%S %z",
                "%a, %d %b %Y %H:%M:%S %Z",
                "%a, %d %b %Y %H:%M:%S",
                "%d %b %Y %H:%M:%S %z",
                "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d",
            ):
                try:
                    parsed = datetime.datetime.strptime(value, fmt)
                    break
                except ValueError:
                    continue

        if parsed is None:
            _logger.info("infohub rss: unparseable feed date %r", value)
            return None

        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        return parsed

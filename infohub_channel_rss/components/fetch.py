"""Outbound HTTP for the RSS channel.

Requests are made with ``allow_redirects=False`` and each hop is re-validated
with ``url_guard``. Following redirects automatically would validate only the
first URL, letting a public feed 302 to ``127.0.0.1`` or the cloud metadata
address ``169.254.169.254`` unchecked.
"""

import logging

import requests

from odoo.addons.component.core import Component
from odoo.addons.infohub.url_guard import UrlNotAllowed, assert_url_allowed

_logger = logging.getLogger(__name__)

#: A declared feed reader is what publishers expect. Some stall or 403 requests
#: carrying a browser User-Agent; others do the opposite, hence the fallback.
USER_AGENTS = (
    "Mozilla/5.0 (compatible; OdooInfoHub/1.0)",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
)
ACCEPT = "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8"

#: (connect, read) — feeds that throttle often stall rather than answer 429.
TIMEOUT = (10, 30)
MAX_REDIRECTS = 5
MAX_BYTES = 10 * 1024 * 1024


class InfohubFetchRss(Component):
    _name = "infohub.fetch.rss"
    _inherit = "infohub.fetch"
    _usage = "infohub.fetch.rss"

    def fetch_news(self, date_from=None, date_to=None, **kwargs):
        channel = self.collection
        if not channel.rss_url:
            raise UrlNotAllowed(
                f"Channel {channel.display_name!r} has no feed URL configured."
            )
        body = self._download(channel.rss_url)
        entries = parse_feed(body)
        return body, entries

    # ------------------------------------------------------------------

    def _download(self, url):
        """GET ``url``, re-validating every redirect hop.

        The body is read with a hard byte cap so a hostile or broken feed cannot
        exhaust memory.
        """
        allow_private = self._allow_private()
        current = url
        last_error = None

        for attempt in USER_AGENTS:
            try:
                return self._download_with_ua(current, allow_private, attempt)
            except requests.RequestException as exc:
                last_error = exc
                _logger.info("infohub rss: %s failed with %r", current, attempt[:30])
        raise last_error

    def _download_with_ua(self, url, allow_private, user_agent):
        headers = {"Accept": ACCEPT, "User-Agent": user_agent}
        current = url

        for _hop in range(MAX_REDIRECTS + 1):
            # Re-check before every request, including the first.
            assert_url_allowed(current, allow_private=allow_private)

            response = requests.get(
                current,
                headers=headers,
                timeout=TIMEOUT,
                allow_redirects=False,
                stream=True,
            )
            try:
                if response.is_redirect or response.is_permanent_redirect:
                    location = response.headers.get("Location")
                    if not location:
                        response.raise_for_status()
                        raise requests.RequestException(
                            f"Redirect without a Location header from {current}"
                        )
                    current = requests.compat.urljoin(current, location)
                    continue
                response.raise_for_status()
                return self._read_bounded(response)
            finally:
                response.close()

        raise requests.RequestException(
            f"Too many redirects (more than {MAX_REDIRECTS}) starting at {url}"
        )

    @staticmethod
    def _read_bounded(response):
        """Read the body, refusing to buffer more than ``MAX_BYTES``.

        Content-Length is used only as an early exit; it is not trusted, so the
        stream is counted as it arrives.
        """
        declared = response.headers.get("Content-Length")
        if declared and declared.isdigit() and int(declared) > MAX_BYTES:
            raise requests.RequestException(
                f"Response too large: {declared} bytes (limit {MAX_BYTES})"
            )

        chunks = []
        total = 0
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_BYTES:
                raise requests.RequestException(
                    f"Response too large: exceeded {MAX_BYTES} bytes"
                )
            chunks.append(chunk)
        return b"".join(chunks)

    def _allow_private(self):
        from odoo.addons.infohub.url_guard import allow_private_from_env

        return allow_private_from_env(self.env)


# ----------------------------------------------------------------------
# Feed parsing
# ----------------------------------------------------------------------

#: Canonical key <- candidate local tag names, in priority order.
ALIASES = (
    ("title", ("title",)),
    ("link", ("link", "origLink", "guid")),
    ("guid", ("guid", "id", "identifier")),
    ("summary", ("description", "summary", "subtitle")),
    ("content", ("encoded", "content")),
    ("published", ("pubDate", "published", "updated", "date", "created")),
    ("author", ("creator", "author", "contributor", "publisher")),
)
CATEGORY_TAGS = ("category", "industry", "subject", "keywords", "tags")
#: Media RSS describes thumbnails and video; its local name ``content`` would
#: otherwise be mistaken for the article body.
SKIP_NAMESPACES = ("http://search.yahoo.com/mrss/",)


def _local(tag):
    """Strip the ``{namespace}`` prefix from an element tag."""
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _namespace(tag):
    """The namespace part of an element tag, without braces."""
    if isinstance(tag, str) and tag.startswith("{"):
        return tag[1:].split("}", 1)[0]
    return ""


def _text(elem):
    """Readable text of ``elem``.

    Some feeds wrap the title in markup, so ``elem.text`` alone comes back
    empty; joining ``itertext`` recovers the label. Elements carrying their
    payload in an attribute — Atom's ``<link href="...">`` — fall back to that.
    """
    value = "".join(elem.itertext()).strip()
    if value:
        return value
    for attr in ("href", "url", "term", "label", "value"):
        if elem.get(attr):
            return elem.get(attr).strip()
    return ""


def _entry_to_dict(entry, feed_title):
    """Flatten one ``<item>`` / ``<entry>`` into a raw_data dict.

    Parsing is deliberately generic rather than per-publisher: every child
    element is kept under its local tag name, so publisher-specific fields stay
    available to ``filter_domain`` without special-casing any of them.
    """
    collected = {}
    categories = []

    for child in entry:
        name = _local(child.tag)
        if not name or _namespace(child.tag) in SKIP_NAMESPACES:
            continue
        value = _text(child)
        if not value:
            continue

        if name in CATEGORY_TAGS:
            if value not in categories:
                categories.append(value)
            continue

        # Atom carries several <link> elements; the alternate (or the first
        # without a rel) is the article, the rest are self/replies.
        if name == "link" and name in collected:
            if child.get("rel") in (None, "alternate"):
                collected[name] = value
            continue

        if name in collected:
            existing = collected[name]
            if isinstance(existing, list):
                if value not in existing:
                    existing.append(value)
            elif value != existing:
                collected[name] = [existing, value]
            continue
        collected[name] = value

    data = {k: v for k, v in collected.items() if not isinstance(v, list) or v}
    for canonical, candidates in ALIASES:
        for candidate in candidates:
            value = collected.get(candidate)
            if isinstance(value, list):
                value = value[0] if value else ""
            if value:
                data[canonical] = value
                break
    if categories:
        data["categories"] = categories
    if feed_title:
        data["feed_title"] = feed_title
    return data


def parse_feed(body):
    """Parse RSS 2.0 / RDF / Atom into a list of raw_data dicts.

    The three layouts disagree on where things live — RSS 2.0 nests items in
    ``<channel>``, RSS 1.0 (RDF) makes them siblings, Atom uses ``<entry>``
    under ``<feed>`` — so entries are located by local tag name anywhere.
    """
    import xml.etree.ElementTree as ET

    if isinstance(body, bytes):
        body = body.decode("utf-8", errors="replace")
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise ValueError(f"Feed is not valid XML: {exc}") from exc

    meta = root
    for elem in root.iter():
        if _local(elem.tag) in ("channel", "feed"):
            meta = elem
            break

    feed_title = ""
    for child in meta:
        if _local(child.tag) == "title":
            feed_title = _text(child)
            break

    entries = [e for e in root.iter() if _local(e.tag) in ("item", "entry")]
    return [_entry_to_dict(entry, feed_title) for entry in entries]

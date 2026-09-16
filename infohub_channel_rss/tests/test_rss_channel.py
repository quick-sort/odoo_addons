from unittest import mock

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.infohub_channel_rss.components.fetch import parse_feed

RSS2 = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel>
    <title>Example Feed</title>
    <item>
      <title>First article</title>
      <link>https://example.com/a1</link>
      <guid isPermaLink="false">guid-1</guid>
      <description>Short &lt;b&gt;summary&lt;/b&gt;</description>
      <pubDate>Thu, 27 Aug 2026 08:39:00 +0000</pubDate>
      <dc:creator>Jane Doe</dc:creator>
      <category>Oncology</category>
      <category>BD</category>
    </item>
  </channel>
</rss>
"""

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Feed</title>
  <entry>
    <title>Atom entry</title>
    <link rel="alternate" href="https://example.org/e1"/>
    <link rel="self" href="https://example.org/self"/>
    <id>urn:uuid:1</id>
    <summary>An atom summary</summary>
    <updated>2026-08-26T17:23:00Z</updated>
  </entry>
</feed>
"""

RDF = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns="http://purl.org/rss/1.0/">
  <channel><title>RDF Feed</title></channel>
  <item>
    <title>RDF item</title>
    <link>https://example.net/r1</link>
    <description>rdf body</description>
  </item>
</rdf:RDF>
"""


@tagged("post_install", "-at_install")
class TestFeedParsing(TransactionCase):
    """The feed parser handles the three layout families, offline."""

    def test_rss2_basics(self):
        entries = parse_feed(RSS2)
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["title"], "First article")
        self.assertEqual(entry["link"], "https://example.com/a1")
        self.assertEqual(entry["guid"], "guid-1")
        self.assertEqual(entry["feed_title"], "Example Feed")

    def test_rss2_collects_categories(self):
        entry = parse_feed(RSS2)[0]
        self.assertEqual(entry["categories"], ["Oncology", "BD"])

    def test_rss2_namespaced_creator_is_kept(self):
        """dc:creator survives under its local name."""
        entry = parse_feed(RSS2)[0]
        self.assertEqual(entry["creator"], "Jane Doe")
        self.assertEqual(entry["author"], "Jane Doe")

    def test_atom_prefers_alternate_link(self):
        """Atom's <link rel="self"> must not win over the article link."""
        entry = parse_feed(ATOM)[0]
        self.assertEqual(entry["link"], "https://example.org/e1")
        self.assertEqual(entry["title"], "Atom entry")
        self.assertEqual(entry["feed_title"], "Atom Feed")

    def test_rdf_items_are_siblings_of_channel(self):
        entries = parse_feed(RDF)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["title"], "RDF item")
        self.assertEqual(entries[0]["feed_title"], "RDF Feed")

    def test_invalid_xml_raises_value_error(self):
        with self.assertRaises(ValueError):
            parse_feed("<not-xml")

    def test_empty_feed_returns_no_entries(self):
        self.assertEqual(parse_feed("<rss><channel><title>x</title></channel></rss>"), [])

    def test_mediarss_content_is_not_treated_as_body(self):
        """Media RSS thumbnails share the local name 'content'."""
        feed = """<?xml version="1.0"?>
        <rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
          <channel><title>T</title>
            <item>
              <title>With image</title>
              <media:content url="https://cdn.example/i.jpg"/>
              <description>real body</description>
            </item>
          </channel>
        </rss>"""
        entry = parse_feed(feed)[0]
        self.assertEqual(entry.get("content", ""), "")
        self.assertEqual(entry["description"], "real body")


@tagged("post_install", "-at_install")
class TestRssChannel(TransactionCase):
    """Channel-level behaviour: URL validation and end-to-end ingest."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Channel = cls.env["infohub.channel"]

    def _channel(self, url="https://example.com/feed.xml", **vals):
        return self.Channel.create(
            {"name": "Feed", "channel_type": "rss", "rss_url": url, **vals}
        )

    def test_rss_is_a_selectable_channel_type(self):
        selection = dict(self.Channel._fields["channel_type"].selection)
        self.assertIn("rss", selection)

    def test_rejects_non_http_feed_url(self):
        with self.assertRaises(ValidationError):
            self._channel("file:///etc/passwd")

    def test_rejects_literal_private_ip(self):
        with self.assertRaises(ValidationError):
            self._channel("http://127.0.0.1/feed")

    def test_rejects_metadata_service_address(self):
        """169.254.169.254 is the cloud metadata endpoint."""
        with self.assertRaises(ValidationError):
            self._channel("http://169.254.169.254/latest/meta-data/")

    def test_accepts_public_feed_url(self):
        self.assertTrue(self._channel("https://example.com/feed.xml").id)

    def test_blank_url_is_allowed_until_fetch(self):
        """A channel can be created before its URL is filled in."""
        self.assertTrue(self._channel(url=False).id)

    def test_fetch_without_url_raises(self):
        channel = self._channel(url=False)
        from odoo.addons.infohub.url_guard import UrlNotAllowed

        with self.assertRaises(UrlNotAllowed):
            channel.fetch_news()

    def _stub_http(self, body):
        """Patch ``requests.get`` at the transport seam.

        Returns a context manager; the response it hands back is a plain
        stand-in exposing only what ``_download_with_ua`` touches. Chunks are
        bytes, as ``iter_content`` yields on a real response.
        """
        payload = body.encode("utf-8")
        response = mock.MagicMock()
        response.is_redirect = False
        response.is_permanent_redirect = False
        response.headers = {"Content-Length": str(len(payload))}
        response.iter_content.return_value = [payload]
        return mock.patch(
            "odoo.addons.infohub_channel_rss.components.fetch.requests.get",
            return_value=response,
        )

    def test_fetch_and_ingest_end_to_end(self):
        """HTTP is stubbed; parsing, ingestion and source linking are real."""
        channel = self._channel()
        source = self.env["infohub.source"].create(
            {"name": "Example Feed", "url": "https://example.com"}
        )

        with self._stub_http(RSS2):
            channel.action_fetch()

        item = self.env["infohub.item"].search([("channel_id", "=", channel.id)])
        self.assertEqual(len(item), 1)
        self.assertEqual(item.title, "First article")
        self.assertEqual(item.url, "https://example.com/a1")
        self.assertEqual(
            item.published_at,
            fields.Datetime.to_datetime("2026-08-27 08:39:00"),
        )
        # feed_title matched the source by name
        self.assertEqual(item.source_id, source)

    def test_refetch_does_not_duplicate(self):
        channel = self._channel()
        with self._stub_http(RSS2):
            channel.action_fetch()
            channel.action_fetch()
        self.assertEqual(channel.item_count, 1)

    def test_fetch_failure_is_recorded_and_reraised(self):
        """A transport error reaches ``_register_failure`` and is re-raised.

        The counters themselves are written on a separate cursor and only land
        for a row the caller has already committed, which a ``TransactionCase``
        never does. So the cross-cursor write is asserted at the seam
        (``_register_failure`` was reached, with the original exception) and the
        counters are left to the failure path itself.
        """
        import requests

        channel = self._channel()
        seen = []

        with mock.patch.object(
            type(channel),
            "_register_failure",
            lambda self, exc: seen.append(exc),
            create=True,
        ), mock.patch(
            "odoo.addons.infohub_channel_rss.components.fetch.requests.get",
            side_effect=requests.RequestException("boom"),
        ):
            with self.assertRaises(requests.RequestException):
                channel.action_fetch()

        self.assertEqual(len(seen), 1)
        self.assertIsInstance(seen[0], requests.RequestException)
        self.assertIn("boom", str(seen[0]))

    def test_register_failure_never_masks_the_cause(self):
        """Bookkeeping failures are swallowed, never replacing the real error."""
        channel = self._channel()
        with mock.patch.object(
            type(channel), "with_env", side_effect=OSError("bookkeeping broke")
        ):
            # Must not raise: the caller is about to re-raise the fetch error,
            # which is the one the user needs to see.
            channel._register_failure(ValueError("original"))

    def test_successful_fetch_clears_error_state(self):
        channel = self._channel()
        channel.write({"error_count": 3, "last_error": "old failure"})
        with self._stub_http(RSS2):
            channel.action_fetch()
        channel.invalidate_recordset()
        self.assertEqual(channel.error_count, 0)
        self.assertFalse(channel.last_error)

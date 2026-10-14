import os
from datetime import timedelta
from unittest import mock

from lxml import etree

from odoo import fields
from odoo.modules.module import get_manifest, get_module_path
from odoo.tests.common import tagged

from odoo.addons.component.tests.common import (
    TransactionComponentCase,
    TransactionComponentRegistryCase,
)

from .common import selection_value, stub_channel_components

# A channel type the core does not know about, standing in for a real channel
# addon.
STUB = "test_stub"


@tagged("post_install", "-at_install")
class TestInfohubCore(TransactionComponentCase):
    """Core models: source, channel, item, and the ingestion path."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Source = cls.env["infohub.source"]
        cls.Item = cls.env["infohub.item"]

    def _make_channel(self, **vals):
        """Create a channel of the stub type.

        ``channel_type`` is a static Selection validated on write, so the stub
        value has to be registered around the create.
        """
        with selection_value(self.env["infohub.channel"], "channel_type", STUB):
            channel = self.env["infohub.channel"].create(
                {"name": "Test channel", "channel_type": STUB, **vals}
            )
        return channel

    # -- model basics ----------------------------------------------------

    def test_source_is_separate_from_channel(self):
        """A source and a channel are independent records."""
        source = self.Source.create({"name": "Nature", "url": "https://nature.com"})
        self.assertEqual(source.name, "Nature")
        self.assertEqual(source.item_count, 0)

    def test_item_requires_title_and_channel(self):
        """title and channel_id are the only required fields."""
        fields_required = self.Item.fields_get(["title", "channel_id"], ["required"])
        self.assertTrue(fields_required["title"]["required"])
        self.assertTrue(fields_required["channel_id"]["required"])

    def test_channel_type_is_extended_by_channel_addons(self):
        """The core ships the extension point; channel addons fill it in.

        With only the core installed the selection is empty; each channel addon
        contributes its own value via ``selection_add``. Either way the field
        itself must exist and be required, which is what the core guarantees.
        """
        field = self.env["infohub.channel"]._fields["channel_type"]
        self.assertTrue(field.required)
        self.assertIsInstance(field.selection, list)
        # Any installed channel addon's values must be well-formed pairs.
        for value, label in field.selection:
            self.assertIsInstance(value, str)
            self.assertIsInstance(label, str)

    def test_core_does_not_depend_on_llm(self):
        """Hard constraint: the core must stay free of the LLM stack."""
        depends = self.env["ir.module.module"].search(
            [("name", "=", "infohub")]
        ).dependencies_id.mapped("name")
        self.assertNotIn("llm", depends)
        self.assertEqual(sorted(depends), ["base", "component", "queue_job"])

    # -- views -----------------------------------------------------------

    def test_item_form_hooks_both_payload_fields(self):
        """Each payload field carries the class its stylesheet targets.

        Both tabs overflow the form as Odoo renders them by default: the json
        widget prints ``JSON.stringify()`` output, which has no whitespace to
        break at, and the html field collapses the payload's own newlines into
        spaces. Which CSS properties fix that cannot be asserted from Python,
        so what this asserts is that the view still carries the hooks the
        stylesheet is written against — losing one brings its overflow back
        with a green suite.
        """
        arch = self.env.ref("infohub.view_infohub_item_form").arch
        root = etree.fromstring(arch.encode())
        for field_name, hook in (
            ("content", "o_infohub_item_content"),
            ("raw_data", "o_infohub_raw_data"),
        ):
            field = root.xpath(f"//field[@name='{field_name}']")
            self.assertEqual(len(field), 1)
            # Whole-token match: a renamed `o_infohub_raw_data_2` is not styled.
            classes = (field[0].get("class") or "").split()
            self.assertIn(hook, classes, f"{field_name} lost its styling hook")

    def test_item_form_stylesheet_is_shipped(self):
        """The wrapping rules must actually reach the browser.

        A stylesheet left out of the backend bundle, or a manifest entry
        pointing at a file nobody committed, is dead weight: the view keeps its
        hooks, every test stays green, and the payloads still overflow. Odoo 19
        materialises no ``ir.asset`` rows for manifest entries — the manifest
        and the file on disk are what get checked instead.
        """
        relative = "static/src/scss/infohub_item.scss"
        manifest = get_manifest("infohub")
        self.assertIn(f"infohub/{relative}", manifest["assets"]["web.assets_backend"])
        self.assertTrue(
            os.path.isfile(os.path.join(get_module_path("infohub"), relative))
        )

    # -- content_text derivation ----------------------------------------

    def test_content_text_derived_from_html(self):
        """Plain-text copy is derived on create, for searching.

        ``html2plaintext`` converts emphasis to Markdown, so ``<b>`` becomes
        ``*bold*`` rather than being stripped.
        """
        item = self.Item.create(
            {
                "title": "Hello",
                "channel_id": self._make_channel().id,
                "content": "<p>Some <b>bold</b> text</p>",
            }
        )
        self.assertEqual(item.content_text, "Some *bold* text")

    def test_content_text_strips_tags(self):
        """Markup itself never survives into the searchable copy."""
        item = self.Item.create(
            {
                "title": "Hello",
                "channel_id": self._make_channel().id,
                "content": "<div><p>Alpha</p><p>Beta</p></div>",
            }
        )
        self.assertNotIn("<", item.content_text)
        self.assertIn("Alpha", item.content_text)
        self.assertIn("Beta", item.content_text)

    def test_explicit_content_text_is_preserved(self):
        item = self.Item.create(
            {
                "title": "Hello",
                "channel_id": self._make_channel().id,
                "content": "<p>ignored</p>",
                "content_text": "kept",
            }
        )
        self.assertEqual(item.content_text, "kept")

    # -- dedup constraint ------------------------------------------------

    def test_duplicate_external_id_in_same_channel_is_rejected(self):
        from psycopg2 import IntegrityError

        channel = self._make_channel()
        self.Item.create(
            {"title": "A", "channel_id": channel.id, "external_id": "x-1"}
        )
        with self.assertRaises(IntegrityError), self.cr.savepoint():
            self.Item.create(
                {"title": "B", "channel_id": channel.id, "external_id": "x-1"}
            )

    def test_same_external_id_in_different_channels_is_allowed(self):
        """The same upstream id under two channels is two distinct items."""
        a, b = self._make_channel(name="A"), self._make_channel(name="B")
        self.Item.create({"title": "A", "channel_id": a.id, "external_id": "x-1"})
        item = self.Item.create(
            {"title": "B", "channel_id": b.id, "external_id": "x-1"}
        )
        self.assertTrue(item.id)

    # -- filter domain evaluation ---------------------------------------

    def test_match_item_simple_equality(self):
        channel = self._make_channel(filter_domain=[["source", "=", "Reuters"]])
        self.assertTrue(channel.match_item({"source": "Reuters"}))
        self.assertFalse(channel.match_item({"source": "AP"}))

    def test_match_item_ilike_is_case_insensitive(self):
        channel = self._make_channel(filter_domain=[["title", "ilike", "cancer"]])
        self.assertTrue(channel.match_item({"title": "New CANCER study"}))
        self.assertFalse(channel.match_item({"title": "unrelated"}))

    def test_match_item_empty_domain_keeps_everything(self):
        channel = self._make_channel(filter_domain=[])
        self.assertTrue(channel.match_item({"anything": 1}))

    def test_match_item_or_expression(self):
        channel = self._make_channel(
            filter_domain=["|", ["a", "=", 1], ["b", "=", 2]]
        )
        self.assertTrue(channel.match_item({"a": 1, "b": 0}))
        self.assertTrue(channel.match_item({"a": 0, "b": 2}))
        self.assertFalse(channel.match_item({"a": 0, "b": 0}))

    def test_match_item_not_expression(self):
        channel = self._make_channel(filter_domain=["!", ["a", "=", 1]])
        self.assertFalse(channel.match_item({"a": 1}))
        self.assertTrue(channel.match_item({"a": 2}))

    def test_match_item_missing_field_with_negative_operator(self):
        """`not ilike` on a missing key should keep the item."""
        channel = self._make_channel(filter_domain=[["x", "not ilike", "y"]])
        self.assertTrue(channel.match_item({}))

    # -- external id extraction ------------------------------------------

    def test_external_id_prefers_guid_over_url(self):
        got = self.env["infohub.channel"]._external_id(
            {"guid": "g-1", "url": "http://x/1"}, {}
        )
        self.assertEqual(got, "g-1")

    def test_external_id_falls_back_to_url(self):
        got = self.env["infohub.channel"]._external_id({"url": "http://x/1"}, {})
        self.assertEqual(got, "http://x/1")

    def test_external_id_empty_when_nothing_usable(self):
        self.assertEqual(self.env["infohub.channel"]._external_id({}, {}), "")

    # -- date parsing -----------------------------------------------------

    def test_published_at_falls_back_to_now_on_garbage(self):
        channel = self._make_channel()
        got = channel._published_at({"published_date": "not-a-date"}, {})
        self.assertTrue(got)

    def test_published_at_parses_iso(self):
        channel = self._make_channel()
        got = channel._published_at({"published_date": "2026-03-04 05:06:07"}, {})
        self.assertEqual(str(got), "2026-03-04 05:06:07")

    # -- scheduled fetch filtering ---------------------------------------

    def _run_cron(self):
        """Run the cron and return the ids of the channels it enqueued."""
        enqueued = []

        def fake_with_delay(record, **kwargs):
            enqueued.append(record.id)
            return mock.MagicMock()

        Channel = self.env["infohub.channel"]
        with mock.patch.object(type(Channel), "with_delay", fake_with_delay):
            Channel._cron_fetch_channels()
        return enqueued

    def test_cron_enqueues_never_run_channel(self):
        channel = self._make_channel(name="Never", enable_cron=True)
        self.assertIn(channel.id, self._run_cron())

    def test_cron_skips_recently_run_channel(self):
        channel = self._make_channel(
            name="Recent", enable_cron=True, last_run_at=fields.Datetime.now()
        )
        self.assertNotIn(channel.id, self._run_cron())

    def test_cron_enqueues_stale_channel(self):
        channel = self._make_channel(
            name="Stale",
            enable_cron=True,
            last_run_at=fields.Datetime.now() - timedelta(hours=2),
        )
        self.assertIn(channel.id, self._run_cron())

    def test_cron_respects_fetch_interval(self):
        now = fields.Datetime.now()
        not_yet = self._make_channel(
            name="Daily",
            enable_cron=True,
            fetch_interval_minutes=1440,
            last_run_at=now - timedelta(hours=1),
        )
        stale = self._make_channel(
            name="Daily stale",
            enable_cron=True,
            fetch_interval_minutes=1440,
            last_run_at=now - timedelta(hours=25),
        )
        enqueued = self._run_cron()
        self.assertNotIn(not_yet.id, enqueued)
        self.assertIn(stale.id, enqueued)

    def test_cron_skips_disabled_channels(self):
        channel = self._make_channel(name="Off", enable_cron=False)
        self.assertNotIn(channel.id, self._run_cron())


@tagged("post_install", "-at_install")
class TestIngestion(TransactionComponentRegistryCase):
    """The shared ingestion path, driven through a stub channel type.

    ``_ingest`` resolves ``infohub.content.<type>`` to read a title off the raw
    payload, so the stub's components must be in the registry. They are built
    with ``_build_components`` into this test's isolated registry, never the
    database-wide one.
    """

    def setUp(self):
        super().setUp()
        self._setup_registry(self)
        self.addCleanup(self._teardown_registry, self)
        # infohub is the addon under test, so _setup_registry excluded it: load
        # its components explicitly to get the infohub.fetch / infohub.content
        # abstract bases the stubs inherit from.
        self._load_module_components("infohub")

        self.items = []
        Fetch, Content = stub_channel_components(STUB, self.items)
        self._build_components(Fetch, Content)
        self.channel = self._channel("Stub")

    def _channel(self, name, **vals):
        with selection_value(self.env["infohub.channel"], "channel_type", STUB):
            return self.env["infohub.channel"].create(
                {"name": name, "channel_type": STUB, **vals}
            )

    def test_ingest_creates_items(self):
        created, skipped = self.channel._ingest(
            [
                {"title": "One", "url": "http://x/1", "raw_data": {"id": "1"}},
                {"title": "Two", "url": "http://x/2", "raw_data": {"id": "2"}},
            ]
        )
        self.assertEqual((created, skipped), (2, 0))
        self.assertEqual(self.channel.item_count, 2)

    def test_ingest_skips_item_without_title(self):
        created, skipped = self.channel._ingest([{"raw_data": {"id": "no-title"}}])
        self.assertEqual((created, skipped), (0, 1))

    def test_ingest_deduplicates_within_channel(self):
        entries = [{"title": "Once", "raw_data": {"id": "dup-1"}}]
        first, _ = self.channel._ingest(entries)
        second, skipped = self.channel._ingest(entries)
        self.assertEqual(first, 1)
        self.assertEqual((second, skipped), (0, 1))

    def test_ingest_honours_filter_domain(self):
        """filter_domain is evaluated against each item's raw_data."""
        channel = self._channel("Filtered", filter_domain=[["keep", "=", True]])
        created, skipped = channel._ingest(
            [
                {"title": "yes", "raw_data": {"id": "a", "keep": True}},
                {"title": "no", "raw_data": {"id": "b", "keep": False}},
            ]
        )
        self.assertEqual((created, skipped), (1, 1))

    def test_ingest_filter_on_missing_raw_field_drops_item(self):
        """A domain naming a field the payload lacks matches nothing."""
        channel = self._channel("Filtered", filter_domain=[["keep", "=", True]])
        created, skipped = channel._ingest(
            [{"title": "x", "raw_data": {"id": "a"}}]
        )
        self.assertEqual((created, skipped), (0, 1))

    def test_ingest_links_known_source_by_url(self):
        source = self.env["infohub.source"].create(
            {"name": "Nature", "url": "https://www.nature.com"}
        )
        self.channel._ingest(
            [{"title": "T", "url": "https://www.nature.com/articles/x", "raw_data": {"id": "s1"}}]
        )
        item = self.env["infohub.item"].search(
            [("channel_id", "=", self.channel.id), ("external_id", "=", "s1")]
        )
        self.assertEqual(item.source_id, source)

    def test_ingest_leaves_source_empty_when_unknown(self):
        self.channel._ingest(
            [{"title": "T", "url": "https://unknown.example/x", "raw_data": {"id": "s2"}}]
        )
        item = self.env["infohub.item"].search(
            [("channel_id", "=", self.channel.id), ("external_id", "=", "s2")]
        )
        self.assertFalse(item.source_id)

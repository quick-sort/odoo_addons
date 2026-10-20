from psycopg2 import IntegrityError

from odoo.tests.common import TransactionCase, tagged

from .common import StubSelectionMixin


@tagged("post_install", "-at_install")
class TestInfohubTag(StubSelectionMixin, TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._open_selections()
        cls.channel = cls._make_channel()
        cls.Tag = cls.env["infohub.tag"]

    def _make_item(self, title):
        return self.env["infohub.item"].create(
            {"channel_id": self.channel.id, "title": title}
        )

    def test_code_is_unique(self):
        self.Tag.create({"name": "Clinical", "code": "test_unique"})
        with self.assertRaises(IntegrityError), self.cr.savepoint():
            self.Tag.create({"name": "Duplicate", "code": "test_unique"})

    def test_tagging_links_items_both_ways(self):
        tag = self.Tag.create({"name": "Clinical", "code": "test_clinical"})
        item = self._make_item("A phase III trial reports ...")
        item.write({"tag_ids": [(6, 0, tag.ids)]})

        self.assertEqual(item.tag_ids, tag)
        self.assertEqual(tag.item_ids, item)
        self.assertEqual(tag.item_count, 1)

    def test_archived_tag_leaves_the_taxonomy(self):
        tag = self.Tag.create({"name": "Clinical", "code": "test_archived"})
        tag.active = False
        self.assertNotIn(tag, self.Tag.search([]))

    def test_tag_type_defaults_to_event(self):
        """Existing/manual tags keep working as event-type entries."""
        tag = self.Tag.create({"name": "Something", "code": "test_event"})
        self.assertEqual(tag.tag_type, "event")

    def test_seeded_taxonomy_covers_both_dimensions(self):
        """The shipped taxonomy classifies both what and where.

        Managers may rename or archive entries, but a deployment that never
        touched the taxonomy must come with enough tags to tag the pool: both
        dimensions are present and the core news types exist.
        """
        tags = self.Tag.search([])
        self.assertTrue(tags.filtered(lambda tag: tag.tag_type == "event"))
        self.assertTrue(tags.filtered(lambda tag: tag.tag_type == "area"))
        codes = set(tags.mapped("code"))
        self.assertTrue({"clinical", "regulatory", "licensing"} <= codes)
        self.assertTrue({"oncology", "immunology", "metabolic"} <= codes)

    def test_new_item_starts_pending(self):
        self.assertEqual(self._make_item("Some headline").tagging_state, "pending")

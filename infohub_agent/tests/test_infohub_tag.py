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
        self.Tag.create({"name": "Clinical", "code": "clinical"})
        with self.assertRaises(IntegrityError), self.cr.savepoint():
            self.Tag.create({"name": "Duplicate", "code": "clinical"})

    def test_tagging_links_items_both_ways(self):
        tag = self.Tag.create({"name": "Clinical", "code": "clinical"})
        item = self._make_item("A phase III trial reports ...")
        item.write({"tag_ids": [(6, 0, tag.ids)]})

        self.assertEqual(item.tag_ids, tag)
        self.assertEqual(tag.item_ids, item)
        self.assertEqual(tag.item_count, 1)

    def test_archived_tag_leaves_the_taxonomy(self):
        tag = self.Tag.create({"name": "Clinical", "code": "clinical"})
        tag.active = False
        self.assertNotIn(tag, self.Tag.search([]))

    def test_new_item_starts_pending(self):
        self.assertEqual(self._make_item("Some headline").tagging_state, "pending")

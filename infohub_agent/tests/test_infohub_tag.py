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
        self.Tag.create({"name": "Clinical", "code": "test_clinical"})
        with self.assertRaises(IntegrityError), self.cr.savepoint():
            self.Tag.create({"name": "Duplicate", "code": "test_clinical"})

    def test_tagging_links_items_both_ways(self):
        tag = self.Tag.create({"name": "Clinical", "code": "test_clinical"})
        item = self._make_item("A phase III trial reports ...")
        item.write({"tag_ids": [(6, 0, tag.ids)]})

        self.assertEqual(item.tag_ids, tag)
        self.assertEqual(tag.item_ids, item)
        self.assertEqual(tag.item_count, 1)

    def test_item_count_reads_for_multiple_tags(self):
        """The list view computes item_count on a batch of tags.

        ``item_ids`` is the inverse of ``infohub.item.tag_ids``, a many2many;
        modelling it as a one2many made the ORM treat the related recordset as
        a singleton and fail as soon as more than one tag was read.
        """
        tag_a = self.Tag.create({"name": "A", "code": "test_count_a"})
        tag_b = self.Tag.create({"name": "B", "code": "test_count_b"})
        item = self._make_item("A phase III trial reports ...")
        item.write({"tag_ids": [(6, 0, (tag_a | tag_b).ids)]})

        self.assertEqual((tag_a | tag_b).mapped("item_count"), [1, 1])

    def test_archived_tag_leaves_the_taxonomy(self):
        tag = self.Tag.create({"name": "Clinical", "code": "test_clinical"})
        tag.active = False
        self.assertNotIn(tag, self.Tag.search([]))

    def test_new_item_starts_pending(self):
        self.assertEqual(self._make_item("Some headline").tagging_state, "pending")

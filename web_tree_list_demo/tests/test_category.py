from odoo.tests.common import TransactionCase


class TestCategory(TransactionCase):
    def test_tree_structure(self):
        Category = self.env["web_tree_list_demo.category"]
        root = Category.create({"name": "Root"})
        child = Category.create({"name": "Child", "parent_id": root.id})
        grandchild = Category.create({"name": "Grandchild", "parent_id": child.id})

        self.assertEqual(child.parent_id, root)
        self.assertIn(child, root.child_ids)
        self.assertEqual(grandchild.parent_id, child)
        self.assertIn(grandchild, child.child_ids)

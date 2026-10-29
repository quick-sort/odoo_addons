from odoo.tests.common import TransactionCase


class TestTreeListView(TransactionCase):
    def test_list_view_accepts_tree_list_js_class(self):
        """<list js_class="tree_list"> must pass arch validation on a self-ref model."""
        view = self.env["ir.ui.view"].create(
            {
                "name": "tree_list.test.view",
                "model": "res.partner",
                "type": "list",
                "arch": """
                    <list js_class="tree_list" default_group_by="parent_id">
                        <field name="name"/>
                    </list>
                """,
            }
        )
        self.assertTrue(view.id)
        self.assertIn('js_class="tree_list"', view.arch)

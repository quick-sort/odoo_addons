from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestDagViewType(TransactionCase):
    def test_view_type_selection_has_dag(self):
        self.assertIn("dag", dict(self.env["ir.ui.view"]._fields["type"].selection))

    def test_act_window_view_mode_has_dag(self):
        self.assertIn(
            "dag",
            dict(self.env["ir.actions.act_window.view"]._fields["view_mode"].selection),
        )

    def test_get_view_info_exposes_dag(self):
        info = self.env["ir.ui.view"].get_view_info()
        self.assertIn("dag", info)
        self.assertEqual(info["dag"]["display_name"], "DAG")
        self.assertTrue(info["dag"]["multi_record"])

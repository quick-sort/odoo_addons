"""Tests for the InfoHub orchestration guide contributed by infohub_agent."""

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestInfohubGuide(TransactionCase):
    def _make_user(self, login, group_ref):
        return self.env["res.users"].create({
            "name": login,
            "login": login,
            "group_ids": [(4, self.env.ref(group_ref).id)],
        })

    def test_guide_contributed_and_gated(self):
        guide = self.env["llm.tool.guide"].search([("code", "=", "infohub")])
        self.assertTrue(guide)

        retriever = self.env["llm.tool.builtin.guide"]
        index = retriever.odoo_model_guide_retriever()
        self.assertIn("infohub", [g["code"] for g in index["guides"]])
        body = retriever.odoo_model_guide_retriever("infohub")
        self.assertEqual(body["code"], "infohub")
        self.assertIn("infohub.item", body["body"])
        self.assertIn("odoo_record_retriever", body["body"])

    def test_guide_hidden_from_non_infohub_users(self):
        member = self._make_user("guide_member", "infohub.group_infohub_user")
        outsider = self._make_user("guide_outsider", "base.group_user")

        member_codes = [
            g["code"]
            for g in self.env["llm.tool.builtin.guide"]
            .with_user(member)
            .odoo_model_guide_retriever()["guides"]
        ]
        outsider_codes = [
            g["code"]
            for g in self.env["llm.tool.builtin.guide"]
            .with_user(outsider)
            .odoo_model_guide_retriever()["guides"]
        ]

        self.assertIn("infohub", member_codes)
        self.assertNotIn("infohub", outsider_codes)

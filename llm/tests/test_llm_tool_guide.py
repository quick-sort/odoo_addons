"""Tests for ``llm.tool.guide`` and ``odoo_model_guide_retriever``."""

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestToolGuide(TransactionCase):
    def _make_group(self, name):
        return self.env["res.groups"].create({"name": name})

    def _make_user(self, login, group=None):
        values = {
            "name": login,
            "login": login,
            "group_ids": [(4, self.env.ref("base.group_user").id)],
        }
        if group:
            values["group_ids"].append((4, group.id))
        return self.env["res.users"].create(values)

    def _make_guide(self, code, group=None, **kwargs):
        values = {
            "code": code,
            "title": f"Guide {code}",
            "summary": f"Summary {code}",
            "body": f"Body {code}",
            "keyword": code,
        }
        values.update(kwargs)
        if group:
            values["allowed_group_ids"] = [(6, 0, [group.id])]
        return self.env["llm.tool.guide"].create(values)

    def _retrieve(self, user, code=None, query=None):
        return (
            self.env["llm.tool.builtin.guide"]
            .with_user(user)
            .odoo_model_guide_retriever(code=code, query=query)
        )

    def test_readable_guides_filters_by_group(self):
        group = self._make_group("Guide Group")
        other = self._make_group("Other Group")
        self._make_guide("public")
        self._make_guide("restricted", group=group)

        member = self._make_user("guide_member", group)
        outsider = self._make_user("guide_outsider", other)

        member_codes = (
            self.env["llm.tool.guide"].with_user(member)._readable_guides().mapped("code")
        )
        outsider_codes = (
            self.env["llm.tool.guide"].with_user(outsider)._readable_guides().mapped("code")
        )

        self.assertIn("public", member_codes)
        self.assertIn("restricted", member_codes)
        self.assertIn("public", outsider_codes)
        self.assertNotIn("restricted", outsider_codes)

    def test_empty_group_guide_admin_only(self):
        group = self._make_group("Empty Group")
        self._make_guide("admin_only", allowed_group_ids=[(5,)])

        member = self._make_user("empty_guide_member", group)
        admin = self.env.ref("base.user_admin")

        member_codes = (
            self.env["llm.tool.guide"].with_user(member)._readable_guides().mapped("code")
        )
        admin_codes = (
            self.env["llm.tool.guide"].with_user(admin)._readable_guides().mapped("code")
        )

        self.assertNotIn("admin_only", member_codes)
        self.assertIn("admin_only", admin_codes)

    def test_guide_defaults_to_internal_user_group(self):
        self._make_guide("defaulted")
        guide = self.env["llm.tool.guide"].search([("code", "=", "defaulted")])
        self.assertIn(self.env.ref("base.group_user"), guide.allowed_group_ids)

    def test_retriever_returns_groups_without_code(self):
        self._make_guide("alpha")
        self._make_guide("alpha-billing")
        self._make_guide("beta")

        result = self._retrieve(self.env.user)

        self.assertIn("groups", result)
        groups = {g["code"]: g["guide_count"] for g in result["groups"]}
        self.assertEqual(groups["alpha"], 2)
        self.assertEqual(groups["beta"], 1)

    def test_retriever_returns_body_with_code(self):
        self._make_guide("alpha", body="Do alpha things")

        result = self._retrieve(self.env.user, "alpha")

        self.assertEqual(result["code"], "alpha")
        self.assertEqual(result["body"], "Do alpha things")

    def test_retriever_hides_restricted_guide(self):
        group = self._make_group("Retriever Group")
        self._make_guide("secret", group=group)
        outsider = self._make_user("retriever_outsider")

        index = self._retrieve(outsider)
        group_codes = {g["code"] for g in index["groups"]}
        self.assertNotIn("secret", group_codes)

        body = self._retrieve(outsider, "secret")
        self.assertIn("error", body)

    def test_retriever_query_filters_by_substring(self):
        self._make_guide("alpha")
        self._make_guide("alpha-billing")
        self._make_guide("beta")

        result = self._retrieve(self.env.user, query="alpha")

        codes = {g["code"] for g in result["guides"]}
        self.assertEqual(codes, {"alpha", "alpha-billing"})
        self.assertEqual(result["count"], 2)

    def test_retriever_code_precedes_query(self):
        self._make_guide("alpha", body="Body alpha")

        result = self._retrieve(self.env.user, "alpha", query="beta")

        self.assertEqual(result["code"], "alpha")
        self.assertEqual(result["body"], "Body alpha")

    def test_dynamic_description_lists_readable_keywords(self):
        group = self._make_group("Dynamic Group")
        self._make_guide("public")
        self._make_guide("secret", group=group)
        member = self._make_user("dynamic_member", group)
        outsider = self._make_user("dynamic_outsider")

        member_desc = (
            self.env["llm.tool.builtin.guide"]
            .with_user(member)
            ._mcp_dynamic_description()
        )
        outsider_desc = (
            self.env["llm.tool.builtin.guide"]
            .with_user(outsider)
            ._mcp_dynamic_description()
        )

        self.assertIn("public", member_desc)
        self.assertIn("secret", member_desc)
        self.assertIn("public", outsider_desc)
        self.assertNotIn("secret", outsider_desc)

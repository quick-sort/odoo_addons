"""Record-rule coverage for ``llm.tool.allowed_group_ids``.

Regular users only see tools whose allowed groups intersect theirs; an empty
allowed set is administrator-only. Group rules are OR-ed, so the permissive
``base.group_system`` rule lets administrators see everything.
"""

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestLLMToolRecordRule(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.allowed_group = cls.env["res.groups"].create({"name": "Tool Rule Allowed"})
        cls.other_group = cls.env["res.groups"].create({"name": "Tool Rule Other"})
        cls.tool = cls.env["llm.tool"].search([], limit=1)
        cls.tool.allowed_group_ids = [(6, 0, cls.allowed_group.ids)]
        cls.member = cls._make_user("tool_rule_member", cls.allowed_group)
        cls.outsider = cls._make_user("tool_rule_outsider", cls.other_group)
        cls.admin = cls.env.ref("base.user_admin")

    @classmethod
    def _make_user(cls, login, group):
        return cls.env["res.users"].create(
            {
                "name": login,
                "login": login,
                "group_ids": [
                    (4, cls.env.ref("base.group_user").id),
                    (4, group.id),
                ],
            }
        )

    def _visible_tool_ids(self, user):
        return self.env["llm.tool"].with_user(user).search([]).ids

    def test_member_sees_allowed_tool(self):
        self.assertIn(self.tool.id, self._visible_tool_ids(self.member))

    def test_outsider_cannot_see_allowed_tool(self):
        self.assertNotIn(self.tool.id, self._visible_tool_ids(self.outsider))

    def test_admin_sees_all_tools(self):
        all_ids = set(self.env["llm.tool"].search([]).ids)
        self.assertEqual(set(self._visible_tool_ids(self.admin)), all_ids)

    def test_empty_allowed_groups_is_admin_only(self):
        self.tool.allowed_group_ids = [(5,)]
        self.assertNotIn(self.tool.id, self._visible_tool_ids(self.member))
        self.assertIn(self.tool.id, self._visible_tool_ids(self.admin))

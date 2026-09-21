from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestLlmPageWorkflow(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.viewer_group = cls.env.ref("llm_page.group_viewer")
        cls.reviewer_group = cls.env.ref("llm_page.group_reviewer")
        cls.reviewer = cls.env["res.users"].create({
            "name": "Page Reviewer",
            "login": "page_reviewer_x",
            "group_ids": [(6, 0, [
                cls.env.ref("base.group_user").id,
                cls.reviewer_group.id,
            ])],
        })
        cls.plain_user = cls.env["res.users"].create({
            "name": "Plain User",
            "login": "plain_user_x",
            "group_ids": [(6, 0, [cls.env.ref("base.group_user").id])],
        })

    def _page(self, **kw):
        values = {
            "name": "Page",
            "slug": "unique-page-%s" % kw.get("_i", 0),
            "html": "<h1>hi</h1>",
        }
        values.update({k: v for k, v in kw.items() if not k.startswith("_")})
        return self.env["llm.page"].create(values)

    def test_transitions_full_cycle(self):
        page = self._page(_i=1)
        self.assertEqual(page.state, "draft")

        page.action_submit()
        self.assertEqual(page.state, "pending")
        self.assertTrue(page.date_submit)

        page.with_user(self.reviewer).action_approve()
        self.assertEqual(page.state, "published")
        self.assertTrue(page.date_publish)

        page.with_user(self.reviewer).action_unpublish()
        self.assertEqual(page.state, "draft")

    def test_reject_cycle(self):
        page = self._page(_i=2)
        page.action_submit()
        page.with_user(self.reviewer).action_reject("needs work")
        self.assertEqual(page.state, "rejected")
        self.assertEqual(page.reject_reason, "needs work")

        page.action_submit()
        self.assertEqual(page.state, "pending")
        self.assertFalse(page.reject_reason)

    def test_reviewer_only_guards(self):
        page = self._page(_i=3)
        page.action_submit()

        with self.assertRaises(UserError):
            page.with_user(self.plain_user).action_approve()
        with self.assertRaises(UserError):
            page.with_user(self.plain_user).action_reject("nope")
        self.assertEqual(page.state, "pending")

    def test_can_view(self):
        published = self._page(_i=4, state="published")
        self.assertTrue(published._can_view(self.reviewer))
        # viewer group membership grants access
        viewer = self.env["res.users"].create({
            "name": "Viewer",
            "login": "viewer_x",
            "group_ids": [(6, 0, [
                self.env.ref("base.group_user").id,
                self.viewer_group.id,
            ])],
        })
        self.assertTrue(published._can_view(viewer))
        self.assertFalse(published._can_view(self.plain_user))

        draft = self._page(_i=5, state="draft")
        self.assertFalse(draft._can_view(self.plain_user))
        self.assertTrue(draft._can_view(self.reviewer))

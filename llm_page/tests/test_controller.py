from odoo.tests.common import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestLlmPageController(HttpCase):
    def setUp(self):
        super().setUp()
        self.viewer_group = self.env.ref("llm_page.group_viewer")
        self.reviewer_group = self.env.ref("llm_page.group_reviewer")

        self.viewer = self.env["res.users"].create({
            "name": "Viewer",
            "login": "viewer_ctrl",
            "password": "viewer-pass-1",
            "group_ids": [(6, 0, [
                self.env.ref("base.group_user").id,
                self.viewer_group.id,
            ])],
        })
        self.nonmember = self.env["res.users"].create({
            "name": "Non Member",
            "login": "nonmember_ctrl",
            "password": "nonmember-pass-1",
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
        })
        self.reviewer = self.env["res.users"].create({
            "name": "Reviewer",
            "login": "reviewer_ctrl",
            "password": "reviewer-pass-1",
            "group_ids": [(6, 0, [
                self.env.ref("base.group_user").id,
                self.reviewer_group.id,
            ])],
        })

    def _page(self, slug, state):
        return self.env["llm.page"].create({
            "name": slug,
            "slug": slug,
            "html": "<h1 id='marker'>SECRET</h1>",
            "state": state,
            "group_id": self.viewer_group.id,
        })

    def test_published_member_200(self):
        self._page("pub-page", "published")
        self.authenticate("viewer_ctrl", "viewer-pass-1")
        r = self.opener.get(self.base_url() + "/static/pub-page", timeout=10)
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"SECRET", r.content)

    def test_published_nonmember_403(self):
        self._page("pub-page-2", "published")
        self.authenticate("nonmember_ctrl", "nonmember-pass-1")
        r = self.opener.get(self.base_url() + "/static/pub-page-2", timeout=10)
        self.assertEqual(r.status_code, 403)

    def test_unpublished_nonreviewer_404(self):
        self._page("draft-page", "draft")
        self.authenticate("nonmember_ctrl", "nonmember-pass-1")
        r = self.opener.get(self.base_url() + "/static/draft-page", timeout=10)
        self.assertEqual(r.status_code, 404)

    def test_unpublished_reviewer_200(self):
        self._page("pending-page", "pending")
        self.authenticate("reviewer_ctrl", "reviewer-pass-1")
        r = self.opener.get(self.base_url() + "/static/pending-page", timeout=10)
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"SECRET", r.content)

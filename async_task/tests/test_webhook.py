from odoo.tests.common import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestAsyncTaskWebhook(HttpCase):
    def test_unknown_token_returns_404(self):
        # Regression: the webhook used to read the body via
        # request.httprequest.stream, which does not exist on Odoo 19's
        # HTTPRequest and crashed with a 500 before the token lookup. A body
        # with an unknown token must now reach the 404 path.
        r = self.opener.post(
            self.base_url() + "/async-task/webhook/bogus-token",
            data=b"{}",
            timeout=10,
        )
        self.assertEqual(r.status_code, 404)

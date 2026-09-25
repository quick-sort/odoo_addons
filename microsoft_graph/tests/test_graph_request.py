from datetime import timedelta
from unittest import mock

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, tagged

from .common import FakeResponse, _service_module, patch_requests_post, patch_requests_request

_SERVICE = "microsoft.graph.service"


@tagged("post_install", "-at_install")
class TestMicrosoftGraphRequest(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(
            "web.base.url", "https://odoo.example.com"
        )
        cls.application = cls.env["microsoft.graph.application"].create(
            {
                "name": "Contoso Graph App",
                "graph_tenant_id": "tenant-guid",
                "graph_client_id": "client-guid",
                "graph_client_secret": "sekret",
                "graph_scope": "offline_access Files.Read.All",
            }
        )
        cls.env["microsoft.graph.credential"].sudo().create(
            {
                "application_id": cls.application.id,
                "user_id": cls.env.user.id,
                "entra_oid": "oid-1",
                "access_token": "cached-token",
                "refresh_token": "refresh-1",
                "token_expiry": fields.Datetime.now() + timedelta(hours=1),
                "granted_scope": "offline_access Files.Read.All",
            }
        )

    def _request(self, responses, path="/v1.0/me", **kwargs):
        with patch_requests_request(responses) as patched:
            payload = self.env[_SERVICE]._request(
                self.application, "GET", path, **kwargs
            )
        return payload, patched

    def test_request_sends_bearer_token(self):
        payload, patched = self._request(FakeResponse(200, {"id": "oid-1"}))
        self.assertEqual(payload, {"id": "oid-1"})
        headers = patched.call_args[1]["headers"]
        self.assertEqual(headers["Authorization"], "Bearer cached-token")

    def test_request_retries_after_401(self):
        refresh_payload = {"access_token": "rotated", "expires_in": 3600}
        with patch_requests_request(
            [FakeResponse(401), FakeResponse(200, {"id": "oid-1"})]
        ) as patched, patch_requests_post(
            FakeResponse(200, refresh_payload)
        ) as post:
            payload = self.env[_SERVICE]._request(self.application, "GET", "/v1.0/me")
        self.assertEqual(payload, {"id": "oid-1"})
        self.assertEqual(patched.call_count, 2)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(
            post.call_args[1]["data"]["grant_type"], "refresh_token"
        )

    def test_request_retries_after_429(self):
        throttled = FakeResponse(429, headers={"Retry-After": "2"})
        with patch_requests_request(
            [throttled, FakeResponse(200, {"id": "oid-1"})]
        ), mock.patch.object(_service_module().time, "sleep") as sleep:
            payload = self.env[_SERVICE]._request(self.application, "GET", "/v1.0/me")
        self.assertEqual(payload, {"id": "oid-1"})
        self.assertEqual(sleep.call_count, 1)
        self.assertEqual(sleep.call_args[0][0], 2.0)

    def test_request_404_not_found(self):
        with self.assertRaises(FileNotFoundError):
            self._request(FakeResponse(404))

    def test_request_403_access_error(self):
        with self.assertRaises(AccessError):
            self._request(FakeResponse(403))

    def test_request_error_payload_extracted(self):
        failure = FakeResponse(
            500, {"error": {"code": "InternalServerError", "message": "boom"}}
        )
        with self.assertRaises(UserError) as ctx:
            self._request(failure)
        self.assertIn("boom", str(ctx.exception))

    def test_request_rejects_unsafe_url(self):
        for bad in (
            "http://graph.microsoft.com/v1.0/me",
            "https://evil.example/v1.0/me",
        ):
            with self.assertRaises(AccessError), self.cr.savepoint():
                self._request(FakeResponse(200, {}), path=bad)

    def test_request_accepts_graph_continuation_url(self):
        payload, _ = self._request(
            FakeResponse(200, {"id": "oid-1"}),
            path="https://graph.microsoft.com/v1.0/me",
        )
        self.assertEqual(payload, {"id": "oid-1"})

    def test_request_empty_body_returns_empty_dict(self):
        payload, _ = self._request(FakeResponse(200, None))
        self.assertEqual(payload, {})

    def test_request_404_after_retry_propagates(self):
        # 401 then 404: the retry happens and the final status still maps to
        # FileNotFoundError rather than an "after retry" access error.
        refresh_payload = {"access_token": "rotated", "expires_in": 3600}
        with patch_requests_request(
            [FakeResponse(401), FakeResponse(404)]
        ), patch_requests_post(FakeResponse(200, refresh_payload)):
            with self.assertRaises(FileNotFoundError):
                self.env[_SERVICE]._request(self.application, "GET", "/v1.0/me")

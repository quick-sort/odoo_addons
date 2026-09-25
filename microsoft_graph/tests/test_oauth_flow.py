import base64
import hashlib
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase, tagged

from .common import FakeResponse, patch_requests_get, patch_requests_post

_SERVICE = "microsoft.graph.service"


@tagged("post_install", "-at_install")
class TestMicrosoftGraphOAuthFlow(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(
            "web.base.url", "https://odoo.example.com"
        )
        # server.env.mixin fields only persist through write() — values
        # passed to create() are cached but never reach the sparse storage,
        # so later recomputes (sudo reads, cache invalidation) would fall
        # back to the field defaults. Create bare, then write.
        cls.application = cls.env["microsoft.graph.application"].create(
            {"name": "Contoso Graph App"}
        )
        cls.application.write(
            {
                "graph_tenant_id": "tenant-guid",
                "graph_client_id": "client-guid",
                "graph_client_secret": "sekret",
                "graph_scope": "offline_access Files.Read.All",
            }
        )

    def _service(self):
        return self.env[_SERVICE]

    def _credential(self, user=None):
        Credential = self.env["microsoft.graph.credential"].sudo()
        return Credential.search(
            [
                ("application_id", "=", self.application.id),
                ("user_id", "=", (user or self.env.user).id),
            ],
            limit=1,
        )

    def _grant_credential(self, **values):
        return self.env["microsoft.graph.credential"].sudo().create(
            {
                "application_id": self.application.id,
                "user_id": self.env.user.id,
                **values,
            }
        )

    # AC-1

    def test_authorization_action_builds_pkce_url(self):
        action = self._service()._authorization_action(self.application)
        self.assertEqual(action["type"], "ir.actions.act_url")
        parsed = urlparse(action["url"])
        self.assertEqual(parsed.hostname, "login.microsoftonline.com")
        self.assertTrue(parsed.path.startswith("/tenant-guid/oauth2/v2.0/authorize"))
        params = parse_qs(parsed.query)
        self.assertEqual(params["client_id"], ["client-guid"])
        self.assertEqual(params["scope"], ["offline_access Files.Read.All"])
        self.assertEqual(
            params["redirect_uri"], ["https://odoo.example.com/microsoft_graph/oauth/callback"]
        )
        self.assertEqual(params["code_challenge_method"], ["S256"])

        credential = self._credential()
        state = params["state"][0]
        self.assertEqual(credential.oauth_state, state)
        self.assertTrue(credential.oauth_state_expiry)
        verifier = credential.oauth_code_verifier
        expected = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        self.assertEqual(params["code_challenge"], [expected])

    def test_authorization_action_rejects_unsafe_redirect(self):
        for bad in ("//evil.example", "https://evil.example", "web#id=1"):
            with self.assertRaises(AccessError), self.cr.savepoint():
                self._service()._authorization_action(
                    self.application, redirect_to=bad
                )

    # AC-2

    def test_complete_authorization_stores_tokens(self):
        action = self._service()._authorization_action(self.application)
        query = parse_qs(urlparse(action["url"]).query)
        state = query["state"][0]
        verifier = self._credential().oauth_code_verifier
        token_payload = {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
            "scope": "offline_access Files.Read.All",
        }
        me_payload = {"id": "oid-1", "displayName": "Alice"}
        with patch_requests_post(
            FakeResponse(200, token_payload)
        ) as post, patch_requests_get(
            FakeResponse(200, me_payload)
        ):
            credential = self._service()._complete_authorization(
                state, "auth-code", self.env.user
            )
        self.assertEqual(credential.entra_oid, "oid-1")
        self.assertEqual(credential.access_token, "new-access")
        self.assertEqual(credential.refresh_token, "new-refresh")
        self.assertTrue(credential.token_expiry)
        self.assertFalse(credential.oauth_state)
        self.assertFalse(credential.oauth_code_verifier)

        form = post.call_args[1]["data"]
        self.assertEqual(form["grant_type"], "authorization_code")
        self.assertEqual(form["code"], "auth-code")
        self.assertEqual(form["code_verifier"], verifier)

    # AC-3

    def test_complete_authorization_invalid_state(self):
        with self.assertRaises(AccessError):
            self._service()._complete_authorization(
                "no-such-state", "code", self.env.user
            )

    def test_complete_authorization_expired_state(self):
        self._grant_credential(
            oauth_state="stale-state",
            oauth_state_expiry=fields.Datetime.now() - timedelta(minutes=1),
            oauth_code_verifier="verifier",
        )
        with self.assertRaises(AccessError):
            self._service()._complete_authorization(
                "stale-state", "code", self.env.user
            )

    # AC-4

    def test_store_tokens_rejects_identity_change(self):
        self._grant_credential(
            entra_oid="oid-original", access_token="tok", refresh_token="ref"
        )
        with self.assertRaises(AccessError):
            self._service()._store_user_tokens(
                self.application,
                self.env.user,
                {"access_token": "tok2"},
                entra_oid="oid-other",
            )

    # AC-5

    def test_cached_token_avoids_http(self):
        self._grant_credential(
            entra_oid="oid-1",
            access_token="cached",
            refresh_token="ref",
            token_expiry=fields.Datetime.now() + timedelta(hours=1),
        )
        with patch_requests_post(FakeResponse(200, {})) as post:
            token = self._service()._get_access_token(self.application)
        self.assertEqual(token, "cached")
        self.assertFalse(post.call_count)

    def test_expired_token_refreshes(self):
        self._grant_credential(
            entra_oid="oid-1",
            access_token="stale",
            refresh_token="old-refresh",
            token_expiry=fields.Datetime.now() - timedelta(minutes=5),
            granted_scope="offline_access Files.Read.All",
        )
        payload = {
            "access_token": "fresh-access",
            "expires_in": 3600,
            "scope": "offline_access Files.Read.All",
        }
        with patch_requests_post(FakeResponse(200, payload)) as post:
            token = self._service()._get_access_token(self.application)
        self.assertEqual(token, "fresh-access")
        self.assertEqual(post.call_count, 1)
        form = post.call_args[1]["data"]
        self.assertEqual(form["grant_type"], "refresh_token")
        self.assertEqual(form["refresh_token"], "old-refresh")

        credential = self._credential()
        self.assertEqual(credential.access_token, "fresh-access")
        self.assertEqual(credential.refresh_token, "old-refresh")

    # AC-6

    def test_invalid_grant_raises_error(self):
        # A failed refresh must raise; no cleanup write can survive the
        # caller's rollback (same reason infohub does failure bookkeeping
        # on a separate cursor).
        self._grant_credential(
            entra_oid="oid-1",
            access_token="stale",
            refresh_token="old-refresh",
            token_expiry=fields.Datetime.now() - timedelta(minutes=5),
        )
        with patch_requests_post(
            FakeResponse(400, {"error": "invalid_grant"})
        ), self.assertRaises(UserError):
            self._service()._get_access_token(self.application)

    # AC-8

    def test_users_hook_self(self):
        portal = self.env["res.users"].create(
            {
                "name": "Bob",
                "login": "bob@example.com",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        with patch_requests_get(FakeResponse(200, {"id": "oid-bob"})) as me:
            portal._set_microsoft_graph_tokens(self.application, "tok", expires_in=3600)
        self.assertEqual(me.call_count, 1)
        self.assertEqual(self._credential(portal).entra_oid, "oid-bob")
        self.assertEqual(self._credential(portal).access_token, "tok")

    def test_users_hook_other_denied(self):
        admin = self.env.ref("base.user_admin")
        portal = self.env["res.users"].create(
            {
                "name": "Bob",
                "login": "bob2@example.com",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        with self.assertRaises(AccessError):
            admin.with_user(portal)._set_microsoft_graph_tokens(
                self.application, "tok"
            )

    # AC-9

    def test_post_auth_redirect_validation(self):
        service = self._service()
        self.assertEqual(service._sanitize_post_auth_redirect(None), False)
        self.assertEqual(
            service._sanitize_post_auth_redirect("/web#id=1"), "/web#id=1"
        )
        for bad in ("//evil.example", "https://evil.example", "a/b", "\\evil"):
            with self.assertRaises(AccessError), self.cr.savepoint():
                service._sanitize_post_auth_redirect(bad)

    # AC-10

    def test_application_configuration_validation(self):
        incomplete = self.env["microsoft.graph.application"].create(
            {"name": "Incomplete", "graph_tenant_id": "tenant-guid"}
        )
        with self.assertRaises(UserError):
            incomplete._graph_validate_configuration()
        self.application._graph_validate_configuration()

    def test_redirect_uri_requires_base_url(self):
        # web.base.url is a protected default parameter: unlink is refused,
        # blanking the value achieves the same test condition.
        self.env["ir.config_parameter"].sudo().set_param("web.base.url", "")
        with self.assertRaises(UserError):
            self._service()._redirect_uri()

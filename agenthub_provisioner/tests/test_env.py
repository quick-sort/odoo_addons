import os
from unittest import mock

from odoo.exceptions import UserError, ValidationError
from odoo.tests import common, tagged

from .common import ProvisionerCaseMixin


@tagged("post_install", "-at_install")
class TestProvisionerEnv(ProvisionerCaseMixin, common.TransactionCase):
    def _profile(self, **values):
        defaults = {
            "name": "Test LLM",
            "base_url": "http://llm.internal",
            "auth_mode": "api_key",
            "secret": "llm-secret",
            "router_model": "router-model",
            "haiku_model": "haiku-model",
            "sonnet_model": "sonnet-model",
            "opus_model": "opus-model",
        }
        defaults.update(values)
        return self.env["agenthub.provisioner.llm"].create(defaults)

    def test_env_precedence_and_llm_rendering(self):
        self.host.write({"default_env": {"SHARED": "host", "HOST_ONLY": "1"}})
        profile = self._profile(
            extra_env={"SHARED": "llm", "LLM_ONLY": "1"}
        )
        self.deployment.write(
            {
                "llm_profile_id": profile.id,
                "extra_env": {"SHARED": "extra"},
            }
        )

        env = self.deployment._render_env()

        self.assertEqual(env["SHARED"], "extra")
        self.assertEqual(env["HOST_ONLY"], "1")
        self.assertEqual(env["LLM_ONLY"], "1")
        self.assertEqual(env["RELAY_URL"], "ws://relay:8090/v1/agent/ws")
        self.assertEqual(env["RELAY_AGENT_ID"], str(self.agent.id))
        self.assertEqual(env["RELAY_AGENT_TOKEN"], self.agent._provisioner_token())
        self.assertEqual(env["ANTHROPIC_BASE_URL"], "http://llm.internal")
        self.assertEqual(env["ANTHROPIC_API_KEY"], "llm-secret")
        self.assertEqual(env["ANTHROPIC_SMALL_FAST_MODEL"], "router-model")
        self.assertEqual(env["ANTHROPIC_DEFAULT_HAIKU_MODEL"], "haiku-model")
        self.assertEqual(env["ANTHROPIC_DEFAULT_SONNET_MODEL"], "sonnet-model")
        self.assertEqual(env["ANTHROPIC_DEFAULT_OPUS_MODEL"], "opus-model")
        self.assertNotIn("ANTHROPIC_AUTH_TOKEN", env)

    def test_auth_token_mode(self):
        profile = self._profile(auth_mode="auth_token")
        self.deployment.write({"llm_profile_id": profile.id})

        env = self.deployment._render_env()

        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "llm-secret")
        self.assertNotIn("ANTHROPIC_API_KEY", env)

    def test_odoo_mode_env(self):
        self.deployment.write(
            {
                "mode": "odoo_discuss",
                "odoo_api_key": "odoo-secret",
                "odoo_channel_id": 42,
            }
        )

        env = self.deployment._render_env()

        self.assertEqual(
            env["ODOO_URL"],
            self.env["ir.config_parameter"].sudo().get_param("web.base.url"),
        )
        self.assertEqual(env["ODOO_DB"], self.env.cr.dbname)
        self.assertEqual(env["ODOO_LOGIN"], self.service_user.login)
        self.assertEqual(env["ODOO_API_KEY"], "odoo-secret")
        self.assertEqual(env["ODOO_CHANNEL_ID"], "42")
        self.assertNotIn("RELAY_AGENT_TOKEN", env)

    def test_preview_masks_secrets(self):
        profile = self._profile()
        self.deployment.write({"llm_profile_id": profile.id})
        self.deployment.write({"odoo_api_key": "odoo-secret"})

        preview = self.deployment._render_env_preview()
        real = self.deployment._render_env()

        self.assertEqual(preview["RELAY_AGENT_TOKEN"], "***")
        self.assertEqual(preview["ANTHROPIC_API_KEY"], "***")
        self.assertEqual(preview["RELAY_URL"], real["RELAY_URL"])
        self.assertNotEqual(preview["RELAY_AGENT_TOKEN"], real["RELAY_AGENT_TOKEN"])

    def test_invalid_extra_env_key(self):
        self.deployment.write({"extra_env": {"lower_case": "x"}})
        with self.assertRaises(ValidationError):
            self.deployment._render_env()

    def test_extra_env_reserved_key(self):
        self.deployment.write({"extra_env": {"RELAY_AGENT_TOKEN": "mine"}})
        with self.assertRaises(ValidationError):
            self.deployment._render_env()

    def test_extra_env_newline(self):
        self.deployment.write({"extra_env": {"BROKEN": "a\nb"}})
        with self.assertRaises(ValidationError):
            self.deployment._render_env()

    def test_token_stable_and_versioned(self):
        first = self.agent._provisioner_token()
        self.assertEqual(first, self.agent._provisioner_token())

        self.agent.write(
            {"provisioner_token_version": self.agent.provisioner_token_version + 1}
        )
        second = self.agent._provisioner_token()

        self.assertNotEqual(first, second)
        self.deployment._sync_agent_token()
        self.assertEqual(
            self.agent.token_hash, self.agent._hash_token(second)
        )

    def test_sync_agent_token_writes_hash(self):
        self.deployment._sync_agent_token()
        token = self.agent._provisioner_token()
        self.assertEqual(self.agent.token_hash, self.agent._hash_token(token))

    def test_odoo_mode_does_not_sync_relay_token(self):
        self.deployment.write({"mode": "odoo_discuss", "odoo_api_key": "x"})
        self.agent.write({"token_hash": "unchanged"})

        self.deployment._sync_agent_token()

        self.assertEqual(self.agent.token_hash, "unchanged")

    def test_missing_token_secret(self):
        param = self.env["ir.config_parameter"].sudo()
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AGENTHUB_PROVISIONER_TOKEN_SECRET", None)
            param.set_param("agenthub.provisioner.token_secret", False)
            with self.assertRaises(UserError):
                self.agent._provisioner_token()

    def test_spec_hash_stable_and_sensitive(self):
        first = self.deployment._spec_hash()
        self.assertEqual(first, self.deployment._spec_hash())

        self.deployment.write({"extra_env": {"NEW_VALUE": "1"}})
        self.assertNotEqual(first, self.deployment._spec_hash())

    def test_spec_labels_and_defaults(self):
        spec = self.deployment._render_spec()

        self.assertEqual(spec.labels["agenthub.managed"], "true")
        self.assertEqual(spec.labels["agenthub.agent_id"], str(self.agent.id))
        self.assertEqual(
            spec.labels["agenthub.deployment_id"], str(self.deployment.id)
        )
        self.assertEqual(spec.labels["agenthub.config_hash"], spec.config_hash)
        self.assertIn("--relay", spec.command)
        self.assertEqual(
            spec.volumes["%s-home" % self.deployment.container_name],
            {"bind": "/home/agent", "mode": "rw"},
        )

    def test_missing_relay_url(self):
        self.host.write({"default_relay_url": False})
        self.deployment.write({"relay_url": False})
        self.env["ir.config_parameter"].sudo().set_param("agenthub.relay_url", False)

        with self.assertRaises(UserError):
            self.deployment._validate_config()

    def test_odoo_mode_requires_api_key(self):
        self.deployment.write({"mode": "odoo_discuss"})
        with self.assertRaises(UserError):
            self.deployment._validate_config()

    def test_image_allowlist(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "agenthub.provisioner.allowed_images", "example.com/other:*"
        )
        with self.assertRaises(UserError):
            self.deployment._validate_config()

    def test_container_name_validation(self):
        with self.assertRaises(ValidationError):
            self.deployment.write({"container_name": "bad name"})

    def test_volume_validation(self):
        self.deployment.write({"volumes": {"bad": {"mode": "rw"}}})
        with self.assertRaises(ValidationError):
            self.deployment._render_volumes()

    def test_logs_are_masked(self):
        token = self.agent._provisioner_token()
        self.deployment.write({"odoo_api_key": "odoo-secret"})
        self.driver.logs_result = "token=%s key=odoo-secret" % token

        logs = self.deployment._fetch_logs()

        self.assertNotIn(token, logs)
        self.assertNotIn("odoo-secret", logs)
        self.assertIn("***", logs)

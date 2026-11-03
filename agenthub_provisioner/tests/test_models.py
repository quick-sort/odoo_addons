from psycopg2 import IntegrityError

from odoo.exceptions import ValidationError
from odoo.tests import common, tagged

from .common import ProvisionerCaseMixin


@tagged("post_install", "-at_install")
class TestProvisionerModels(ProvisionerCaseMixin, common.TransactionCase):
    def test_llm_requires_router_or_haiku(self):
        with self.assertRaises(ValidationError):
            self.env["agenthub.provisioner.llm"].create(
                {
                    "name": "No Router",
                    "secret": "s",
                    "router_model": False,
                    "haiku_model": False,
                }
            )

    def test_host_probe_success(self):
        self.host.action_probe()

        self.assertEqual(self.host.state, "online")
        self.assertTrue(self.host.last_probe_at)
        self.assertFalse(self.host.last_error)
        self.assertEqual(self.driver.calls[0], ("probe", self.host.id))

    def test_host_probe_failure(self):
        self.driver.fail = "probe"
        self.host.action_probe()

        self.assertEqual(self.host.state, "error")
        self.assertTrue(self.host.last_error)

    def test_deployment_defaults(self):
        self.assertEqual(
            self.deployment.container_name,
            "agenthub-agent-%s" % self.agent.id,
        )
        self.assertEqual(
            self.deployment.image,
            "ghcr.io/quick-sort/agent-box:latest",
        )
        self.assertIn("--relay", self.deployment._command_tuple())
        self.assertEqual(self.deployment.state, "draft")
        self.assertEqual(self.deployment.desired_state, "stopped")

    def test_odoo_mode_default_command(self):
        self.deployment.write({"mode": "odoo_discuss"})
        self.assertIn("--odoo", self.deployment._command_tuple())

    def test_one_deployment_per_agent(self):
        with self.assertRaises(IntegrityError):
            self.env["agenthub.agent.deployment"].create(
                {
                    "agent_id": self.agent.id,
                    "host_id": self.host.id,
                }
            )

    def test_agent_extension_fields(self):
        self.assertEqual(self.agent.provisioner_token_version, 1)
        self.assertEqual(self.agent.deployment_count, 1)
        self.assertEqual(self.agent.deployment_ids, self.deployment)

    def test_agent_open_deployments(self):
        action = self.agent.action_open_deployments()
        self.assertEqual(action["res_model"], "agenthub.agent.deployment")
        self.assertEqual(action["domain"], [("agent_id", "=", self.agent.id)])

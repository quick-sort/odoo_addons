import uuid

from odoo.exceptions import AccessError
from odoo.tests import common, tagged

from .common import ProvisionerCaseMixin


@tagged("post_install", "-at_install")
class TestProvisionerSecurity(ProvisionerCaseMixin, common.TransactionCase):
    def setUp(self):
        super().setUp()
        self.regular_user = self.env["res.users"].create(
            {
                "name": "Regular User",
                "login": "regular_%s" % uuid.uuid4().hex[:8],
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )

    def test_non_system_cannot_create_host(self):
        with self.assertRaises(AccessError):
            self.env["agenthub.provisioner.host"].with_user(
                self.regular_user
            ).create({"name": "Nope", "driver_type": "test"})

    def test_non_system_cannot_read_deployment(self):
        with self.assertRaises(AccessError):
            self.deployment.with_user(self.regular_user).read(["name"])

    def test_non_system_cannot_apply(self):
        with self.assertRaises(AccessError):
            self.deployment.with_user(self.regular_user).action_apply()

    def test_non_system_cannot_open_agent_deployments(self):
        with self.assertRaises(AccessError):
            self.agent.with_user(self.regular_user).action_open_deployments()

    def test_secret_fields_are_system_only(self):
        self.assertEqual(
            self.env["agenthub.provisioner.llm"]._fields["secret"].groups,
            "base.group_system",
        )
        self.assertEqual(
            self.env["agenthub.agent.deployment"]._fields["odoo_api_key"].groups,
            "base.group_system",
        )
        self.assertEqual(
            self.env["agenthub.agent"]._fields[
                "provisioner_token_version"
            ].groups,
            "base.group_system",
        )

import os
import uuid
from unittest import mock

from odoo.addons.agenthub.tests.common import selection_value
from odoo.addons.agenthub_provisioner.contract import (
    ContainerState,
    HostProbe,
    ProvisionerError,
)


class FakeDriver:
    """Deterministic driver used by the core tests; never touches Docker/SSH."""

    def __init__(self):
        self.calls = []
        self.probe_result = HostProbe(True, "test-1.0")
        self.apply_result = None
        self.status_result = None
        self.stop_result = None
        self.remove_result = None
        self.logs_result = "line-1\nline-2"
        self.fail = None

    def probe(self, host):
        self.calls.append(("probe", host.id))
        if self.fail == "probe":
            raise ProvisionerError("UNREACHABLE", "probe failed")
        return self.probe_result

    def apply(self, host, spec):
        self.calls.append(("apply", spec))
        if self.fail == "apply":
            raise ProvisionerError("CREATE_FAILED", "apply failed")
        if self.apply_result is not None:
            return self.apply_result
        return ContainerState(
            id="cid-1",
            name=spec.name,
            status="running",
            labels=dict(spec.labels),
        )

    def stop(self, host, container_id, timeout=10):
        self.calls.append(("stop", container_id, timeout))
        if self.fail == "stop":
            raise ProvisionerError("STOP_FAILED", "stop failed")
        return self.stop_result

    def remove(self, host, container_id):
        self.calls.append(("remove", container_id))
        if self.fail == "remove":
            raise ProvisionerError("REMOVE_FAILED", "remove failed")
        return self.remove_result

    def status(self, host, container_id):
        self.calls.append(("status", container_id))
        if self.fail == "status":
            raise ProvisionerError("UNREACHABLE", "status failed")
        if self.status_result is not None:
            return self.status_result
        return ContainerState(
            id="cid-1",
            name=str(container_id),
            status="running",
            labels={},
        )

    def logs(self, host, container_id, tail=200):
        self.calls.append(("logs", container_id, tail))
        if self.fail == "logs":
            raise ProvisionerError("SSH_COMMAND_FAILED", "logs failed")
        return self.logs_result


class ProvisionerCaseMixin:
    def setUp(self):
        super().setUp()
        self._enter_selection("agenthub.agent", "agent_type", "test")
        self._enter_selection(
            "agenthub.provisioner.host", "driver_type", "test"
        )
        self._secret_patch = mock.patch.dict(
            os.environ, {"AGENTHUB_PROVISIONER_TOKEN_SECRET": "test-secret"}
        )
        self._secret_patch.start()
        self.addCleanup(self._secret_patch.stop)

        self.service_user = self.env["res.users"].create(
            {
                "name": "Provisioner Test User",
                "login": "provisioner_test_%s" % uuid.uuid4().hex[:8],
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        self.agent = self.env["agenthub.agent"].create(
            {
                "name": "Test Agent",
                "agent_type": "test",
                "runtime": "relay",
                "user_id": self.service_user.id,
                "owner_user_id": self.env.user.id,
            }
        )
        self.host = self.env["agenthub.provisioner.host"].create(
            {
                "name": "Test Host",
                "driver_type": "test",
                "default_image": "ghcr.io/quick-sort/agent-box:latest",
                "default_relay_url": "ws://relay:8090/v1/agent/ws",
            }
        )
        self.deployment = self.env["agenthub.agent.deployment"].create(
            {
                "agent_id": self.agent.id,
                "host_id": self.host.id,
                "mode": "relay",
            }
        )
        self.driver = FakeDriver()
        self._patch_driver(self.driver)

    def _enter_selection(self, model, field_name, value):
        manager = selection_value(
            self.env[model], field_name, value, value.title()
        )
        manager.__enter__()
        self.addCleanup(manager.__exit__, None, None, None)

    def _patch_driver(self, driver):
        patcher = mock.patch.object(
            type(self.host), "_driver", lambda record: driver
        )
        patcher.start()
        self.addCleanup(patcher.stop)

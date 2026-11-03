from unittest import mock

from docker.errors import ImageNotFound, NotFound

from odoo.tests import common, tagged

from odoo.addons.agenthub_provisioner.contract import (
    ContainerSpec,
    ProvisionerError,
)
from odoo.addons.agenthub_provisioner_docker.components import (
    driver as driver_module,
)


class FakeImage:
    def __init__(self, tags):
        self.tags = list(tags)


class FakeContainer:
    def __init__(self, name, labels=None, status="running", image=None, cid="cid-1"):
        self.id = cid
        self.name = name
        self.labels = dict(labels or {})
        self.status = status
        self.image = FakeImage([image] if image else [])
        self.attrs = {
            "Config": {"Image": image},
            "State": {"Status": status},
        }
        self.actions = []

    def start(self):
        self.actions.append("start")
        self.status = "running"

    def stop(self, timeout=10):
        self.actions.append(("stop", timeout))
        self.status = "exited"

    def remove(self, force=False):
        self.actions.append(("remove", force))

    def logs(self, tail=200, timestamps=True):
        return b"line-1\nline-2"


class FakeContainers:
    def __init__(self):
        self.items = {}
        self.created = None

    def get(self, name):
        if name not in self.items:
            raise NotFound("not found")
        return self.items[name]

    def create(self, **kwargs):
        self.created = kwargs
        container = FakeContainer(
            name=kwargs["name"],
            labels=kwargs["labels"],
            status="created",
            image=kwargs["image"],
        )
        self.items[kwargs["name"]] = container
        return container


class FakeImages:
    def __init__(self):
        self.images = set()
        self.pulled = []

    def get(self, image):
        if image not in self.images:
            raise ImageNotFound("not found")
        return FakeImage([image])

    def pull(self, image):
        self.pulled.append(image)
        self.images.add(image)
        return FakeImage([image])


class FakeClient:
    def __init__(self):
        self.containers = FakeContainers()
        self.images = FakeImages()

    def ping(self):
        return True

    def version(self):
        return {"Version": "27.0.0"}


@tagged("post_install", "-at_install")
class TestDockerDriver(common.TransactionCase):
    def setUp(self):
        super().setUp()
        self.host = self.env["agenthub.provisioner.host"].create(
            {
                "name": "Docker Host",
                "driver_type": "docker",
                "docker_url": "unix:///var/run/docker.sock",
            }
        )
        self.component = self.host._driver()
        self.client = FakeClient()
        self.client.images.images.add("ghcr.io/quick-sort/agent-box:latest")
        self._client_patcher = mock.patch.object(
            type(self.component), "_client", lambda component, host: self.client
        )
        self._client_patcher.start()
        self.addCleanup(self._client_patcher.stop)

    def _spec(self, **overrides):
        values = {
            "name": "agenthub-agent-1",
            "image": "ghcr.io/quick-sort/agent-box:latest",
            "command": ("uv", "run", "agent-box", "--relay"),
            "env": {"RELAY_URL": "ws://relay:8090/v1/agent/ws"},
            "volumes": {"agent-home": {"bind": "/home/agent", "mode": "rw"}},
            "labels": {
                "agenthub.managed": "true",
                "agenthub.agent_id": "1",
                "agenthub.deployment_id": "10",
                "agenthub.config_hash": "hash-1",
            },
            "config_hash": "hash-1",
            "network": "main",
            "restart_policy": "unless-stopped",
            "pull_policy": "missing",
        }
        values.update(overrides)
        return ContainerSpec(**values)

    def test_driver_resolution(self):
        self.assertEqual(self.component._usage, "docker")

    def test_probe(self):
        probe = self.component.probe(self.host)
        self.assertTrue(probe.ok)
        self.assertEqual(probe.version, "27.0.0")

    def test_apply_creates_and_starts(self):
        spec = self._spec()

        state = self.component.apply(self.host, spec)

        created = self.client.containers.created
        self.assertEqual(created["name"], spec.name)
        self.assertEqual(created["image"], spec.image)
        self.assertEqual(created["command"], list(spec.command))
        self.assertEqual(created["environment"], dict(spec.env))
        self.assertEqual(created["volumes"], dict(spec.volumes))
        self.assertEqual(created["labels"], dict(spec.labels))
        self.assertEqual(created["network"], "main")
        self.assertEqual(created["restart_policy"], {"Name": "unless-stopped"})
        self.assertEqual(
            self.client.containers.items[spec.name].actions, ["start"]
        )
        self.assertEqual(state.status, "running")

    def test_apply_is_idempotent_for_same_hash(self):
        spec = self._spec()
        container = FakeContainer(
            name=spec.name,
            labels=dict(spec.labels),
            status="running",
            image=spec.image,
        )
        self.client.containers.items[spec.name] = container

        self.component.apply(self.host, spec)

        self.assertIsNone(self.client.containers.created)
        self.assertEqual(container.actions, [])

    def test_apply_recreates_on_changed_hash(self):
        spec = self._spec()
        old_labels = dict(spec.labels, **{"agenthub.config_hash": "old"})
        container = FakeContainer(
            name=spec.name,
            labels=old_labels,
            status="running",
            image=spec.image,
        )
        self.client.containers.items[spec.name] = container

        self.component.apply(self.host, spec)

        self.assertIn(("stop", 10), container.actions)
        self.assertIn(("remove", True), container.actions)
        self.assertIsNotNone(self.client.containers.created)
        self.assertEqual(
            self.client.containers.created["labels"]["agenthub.config_hash"],
            "hash-1",
        )

    def test_apply_refuses_unmanaged_container(self):
        spec = self._spec()
        container = FakeContainer(
            name=spec.name,
            labels={},
            status="running",
            image=spec.image,
        )
        self.client.containers.items[spec.name] = container

        with self.assertRaises(ProvisionerError) as caught:
            self.component.apply(self.host, spec)

        self.assertEqual(caught.exception.code, "CONFLICT")
        self.assertEqual(container.actions, [])
        self.assertIsNone(self.client.containers.created)

    def test_apply_refuses_other_deployment(self):
        spec = self._spec()
        labels = dict(spec.labels, **{"agenthub.deployment_id": "99"})
        container = FakeContainer(
            name=spec.name,
            labels=labels,
            status="running",
            image=spec.image,
        )
        self.client.containers.items[spec.name] = container

        with self.assertRaises(ProvisionerError) as caught:
            self.component.apply(self.host, spec)

        self.assertEqual(caught.exception.code, "CONFLICT")

    def test_pull_policy_missing(self):
        self.client.images.images.clear()
        spec = self._spec()

        self.component.apply(self.host, spec)

        self.assertEqual(
            self.client.images.pulled, ["ghcr.io/quick-sort/agent-box:latest"]
        )

    def test_pull_policy_always(self):
        spec = self._spec(pull_policy="always")

        self.component.apply(self.host, spec)

        self.assertEqual(len(self.client.images.pulled), 1)

    def test_pull_policy_never_missing_image(self):
        self.client.images.images.clear()
        spec = self._spec(pull_policy="never")

        with self.assertRaises(ProvisionerError) as caught:
            self.component.apply(self.host, spec)

        self.assertEqual(caught.exception.code, "IMAGE_MISSING")
        self.assertIsNone(self.client.containers.created)

    def test_stop(self):
        container = FakeContainer(name="agent", status="running")
        self.client.containers.items["agent"] = container

        self.component.stop(self.host, "agent", timeout=3)

        self.assertEqual(container.actions, [("stop", 3)])

    def test_stop_missing_is_noop(self):
        self.component.stop(self.host, "missing")

    def test_remove(self):
        container = FakeContainer(name="agent")
        self.client.containers.items["agent"] = container

        self.component.remove(self.host, "agent")

        self.assertEqual(container.actions, [("remove", True)])

    def test_remove_missing_is_noop(self):
        self.component.remove(self.host, "missing")

    def test_status_missing(self):
        state = self.component.status(self.host, "missing")
        self.assertEqual(state.status, "missing")
        self.assertIsNone(state.id)

    def test_status_running_with_labels(self):
        container = FakeContainer(
            name="agent", labels={"agenthub.managed": "true"}, status="running"
        )
        self.client.containers.items["agent"] = container

        state = self.component.status(self.host, "agent")

        self.assertEqual(state.status, "running")
        self.assertEqual(state.labels, {"agenthub.managed": "true"})

    def test_logs(self):
        self.client.containers.items["agent"] = FakeContainer(name="agent")

        self.assertEqual(
            self.component.logs(self.host, "agent"), "line-1\nline-2"
        )

    def test_logs_missing_is_empty(self):
        self.assertEqual(self.component.logs(self.host, "missing"), "")

    def test_invalid_scheme(self):
        self.host.docker_url = "http://docker:2375"
        with self.assertRaises(ProvisionerError) as caught:
            self.component._validate_url(self.host)
        self.assertEqual(caught.exception.code, "INVALID_ENDPOINT")

    def test_non_loopback_tcp_requires_tls(self):
        self.host.docker_url = "tcp://10.0.0.5:2376"
        self.host.docker_tls = False
        with self.assertRaises(ProvisionerError) as caught:
            self.component._validate_url(self.host)
        self.assertEqual(caught.exception.code, "INSECURE_ENDPOINT")

    def test_loopback_tcp_without_tls_is_allowed(self):
        self.host.docker_url = "tcp://127.0.0.1:2375"
        self.host.docker_tls = False
        self.component._validate_url(self.host)

    def test_tls_config(self):
        self.host.write(
            {
                "docker_url": "tcp://docker.example:2376",
                "docker_tls": True,
                "docker_tls_ca": "/ca.pem",
                "docker_tls_cert": "/cert.pem",
                "docker_tls_key": "/key.pem",
            }
        )
        self._client_patcher.stop()

        fake_client = FakeClient()
        with mock.patch.object(
            driver_module.docker, "DockerClient", return_value=fake_client
        ) as docker_cls, mock.patch.object(
            driver_module.docker.tls, "TLSConfig"
        ) as tls_cls:
            client = self.component._client(self.host)

        self.assertIs(client, fake_client)
        tls_cls.assert_called_once_with(
            ca_cert="/ca.pem",
            client_cert=("/cert.pem", "/key.pem"),
            verify=True,
        )
        docker_cls.assert_called_once_with(
            base_url="tcp://docker.example:2376",
            timeout=30,
            tls=tls_cls.return_value,
        )

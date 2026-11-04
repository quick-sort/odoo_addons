import json
from unittest import mock

from odoo.tests import common, tagged

from odoo.addons.agenthub_provisioner.contract import (
    ContainerSpec,
    ProvisionerError,
)


class FakeSsh:
    """Records ``_exec`` calls and mimics the remote docker CLI."""

    def __init__(self):
        self.calls = []
        self.info = None
        self.image_present = True
        self.fail_create = False
        self.version = "27.0.0"
        self.created_argv = None

    def __call__(self, host, argv, stdin=None, check=True):
        argv = list(argv)
        self.calls.append({"argv": argv, "stdin": stdin})
        docker = host.remote_docker or "docker"
        if argv[:2] == [docker, "version"]:
            return 0, self.version + "\n", ""
        if argv[:2] == [docker, "inspect"]:
            if self.info is None:
                if check:
                    raise ProvisionerError("SSH_COMMAND_FAILED", "missing")
                return 1, "", "No such object"
            return 0, json.dumps([self.info]), ""
        if argv[:2] == [docker, "image"]:
            return (0 if self.image_present else 1), "", ""
        if argv[:2] == [docker, "pull"]:
            self.image_present = True
            return 0, "", ""
        if argv[:2] == [docker, "create"]:
            if self.fail_create:
                raise ProvisionerError("SSH_COMMAND_FAILED", "create failed")
            self._record_create(argv)
            return 0, "", ""
        if argv[:2] == [docker, "start"]:
            if self.info:
                self.info["State"]["Status"] = "running"
            return 0, "", ""
        if argv[:2] == [docker, "stop"]:
            if self.info:
                self.info["State"]["Status"] = "exited"
            return 0, "", ""
        if argv[:2] == [docker, "rm"]:
            self.info = None
            return 0, "", ""
        if argv[:2] == [docker, "logs"]:
            return 0, "line-1\n", "line-2\n"
        return 0, "", ""

    def _record_create(self, argv):
        name = argv[argv.index("--name") + 1]
        labels = {}
        index = 0
        while index < len(argv):
            if argv[index] == "--label":
                key, _sep, value = argv[index + 1].partition("=")
                labels[key] = value
                index += 2
            else:
                index += 1
        image = argv[argv.index("--restart") + 2]
        self.info = {
            "Id": "cid-1",
            "Name": "/" + name,
            "State": {"Status": "created"},
            "Config": {"Image": image, "Labels": labels},
            "RepoTags": [image],
        }
        self.created_argv = argv


@tagged("post_install", "-at_install")
class TestSshDriver(common.TransactionCase):
    def setUp(self):
        super().setUp()
        self.host = self.env["agenthub.provisioner.host"].create(
            {
                "name": "SSH Host",
                "driver_type": "ssh",
                "ssh_host": "docker.example",
                "ssh_user": "deploy",
            }
        )
        self.component = self.host._driver()
        self.ssh = FakeSsh()
        patcher = mock.patch.object(
            type(self.component),
            "_exec",
            lambda component, host, argv, stdin=None, check=True: self.ssh(
                host, argv, stdin=stdin, check=check
            ),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _spec(self, **overrides):
        values = {
            "name": "agenthub-agent-1",
            "image": "ghcr.io/quick-sort/agent-box:latest",
            "command": ("uv", "run", "agent-box", "--relay"),
            "env": {
                "RELAY_URL": "ws://relay:8090/v1/agent/ws",
                "RELAY_AGENT_TOKEN": "super-secret",
            },
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

    def _env_path(self):
        for call in self.ssh.calls:
            if call["argv"][:2] == ["sh", "-c"]:
                return call["argv"][2].split("cat > ", 1)[1].strip("'")
        return None

    def test_probe(self):
        probe = self.component.probe(self.host)
        self.assertTrue(probe.ok)
        self.assertEqual(probe.version, "27.0.0")

    def test_apply_creates_env_file_and_container(self):
        spec = self._spec()

        state = self.component.apply(self.host, spec)

        env_path = self._env_path()
        self.assertTrue(env_path)
        env_write = [
            call
            for call in self.ssh.calls
            if call["argv"][:2] == ["sh", "-c"]
        ][0]
        self.assertIn("umask 077", env_write["argv"][2])
        self.assertIn("RELAY_URL=ws://relay:8090/v1/agent/ws", env_write["stdin"])
        self.assertIn("RELAY_AGENT_TOKEN=super-secret", env_write["stdin"])

        argv = self.ssh.created_argv
        self.assertIn("--env-file", argv)
        self.assertEqual(argv[argv.index("--env-file") + 1], env_path)
        self.assertNotIn("super-secret", " ".join(argv))
        self.assertIn("--network", argv)
        self.assertIn("main", argv)
        self.assertIn("-v", argv)
        self.assertIn("agent-home:/home/agent:rw", argv)
        self.assertIn("--restart", argv)
        self.assertIn("ghcr.io/quick-sort/agent-box:latest", argv)
        self.assertIn("--relay", argv)
        self.assertIn(["rm", "-f", env_path], [call["argv"] for call in self.ssh.calls])
        self.assertEqual(state.status, "running")

    def test_apply_is_idempotent_for_same_hash(self):
        spec = self._spec()
        self.ssh.info = {
            "Id": "cid-1",
            "Name": "/" + spec.name,
            "State": {"Status": "running"},
            "Config": {"Image": spec.image, "Labels": dict(spec.labels)},
            "RepoTags": [spec.image],
        }

        self.component.apply(self.host, spec)

        self.assertFalse(
            any(call["argv"][:2] == ["docker", "create"] for call in self.ssh.calls)
        )
        self.assertFalse(
            any(call["argv"][:2] == ["docker", "stop"] for call in self.ssh.calls)
        )

    def test_apply_recreates_in_order(self):
        spec = self._spec()
        labels = dict(spec.labels, **{"agenthub.config_hash": "old"})
        self.ssh.info = {
            "Id": "cid-1",
            "Name": "/" + spec.name,
            "State": {"Status": "running"},
            "Config": {"Image": spec.image, "Labels": labels},
            "RepoTags": [spec.image],
        }

        self.component.apply(self.host, spec)

        methods = [
            call["argv"][1]
            for call in self.ssh.calls
            if call["argv"][0] == "docker" and len(call["argv"]) > 1
        ]
        stop_index = methods.index("stop")
        rm_index = methods.index("rm")
        create_index = methods.index("create")
        start_index = methods.index("start")
        self.assertLess(stop_index, rm_index)
        self.assertLess(rm_index, create_index)
        self.assertLess(create_index, start_index)

    def test_apply_refuses_unmanaged_container(self):
        spec = self._spec()
        self.ssh.info = {
            "Id": "cid-1",
            "Name": "/" + spec.name,
            "State": {"Status": "running"},
            "Config": {"Image": spec.image, "Labels": {}},
        }

        with self.assertRaises(ProvisionerError) as caught:
            self.component.apply(self.host, spec)

        self.assertEqual(caught.exception.code, "CONFLICT")
        self.assertFalse(
            any(call["argv"][:2] == ["docker", "create"] for call in self.ssh.calls)
        )

    def test_pull_policy_never_missing_image(self):
        self.ssh.image_present = False
        spec = self._spec(pull_policy="never")

        with self.assertRaises(ProvisionerError) as caught:
            self.component.apply(self.host, spec)

        self.assertEqual(caught.exception.code, "IMAGE_MISSING")

    def test_env_file_cleanup_on_create_failure(self):
        self.ssh.fail_create = True
        spec = self._spec()

        with self.assertRaises(ProvisionerError) as caught:
            self.component.apply(self.host, spec)

        self.assertEqual(caught.exception.code, "CREATE_FAILED")
        env_path = self._env_path()
        self.assertIn(["rm", "-f", env_path], [call["argv"] for call in self.ssh.calls])

    def test_stop(self):
        self.ssh.info = {
            "Id": "cid-1",
            "Name": "/agent",
            "State": {"Status": "running"},
            "Config": {"Image": "img", "Labels": {}},
        }

        self.component.stop(self.host, "agent", timeout=3)

        call = [c for c in self.ssh.calls if c["argv"][:2] == ["docker", "stop"]][0]
        self.assertEqual(call["argv"], ["docker", "stop", "-t", "3", "agent"])

    def test_stop_missing_is_noop(self):
        self.component.stop(self.host, "missing")
        self.assertFalse(any(c["argv"][:2] == ["docker", "stop"] for c in self.ssh.calls))

    def test_remove(self):
        self.ssh.info = {
            "Id": "cid-1",
            "Name": "/agent",
            "State": {"Status": "running"},
            "Config": {"Image": "img", "Labels": {}},
        }

        self.component.remove(self.host, "agent")

        self.assertIn(["docker", "rm", "-f", "agent"], [c["argv"] for c in self.ssh.calls])

    def test_status_missing(self):
        state = self.component.status(self.host, "missing")
        self.assertEqual(state.status, "missing")

    def test_status_running(self):
        self.ssh.info = {
            "Id": "cid-1",
            "Name": "/agent",
            "State": {
                "Status": "running",
                "Health": {"Status": "healthy"},
            },
            "Config": {"Image": "img", "Labels": {"agenthub.managed": "true"}},
        }

        state = self.component.status(self.host, "agent")

        self.assertEqual(state.status, "running")
        self.assertEqual(state.health, "healthy")
        self.assertEqual(state.labels, {"agenthub.managed": "true"})

    def test_logs_combines_stdout_and_stderr(self):
        self.assertEqual(
            self.component.logs(self.host, "agent"),
            "line-1\nline-2\n",
        )

    def test_command_quoting(self):
        command = self.component._command(
            ["docker", "run", "name; rm -rf /", "$(touch /tmp/x)"]
        )
        self.assertIn("'name; rm -rf /'", command)
        self.assertIn("'$(touch /tmp/x)'", command)

    def _fake_connect(self, fake_client):
        fake_paramiko = FakeParamiko(fake_client)
        paramiko_patch = mock.patch.object(
            type(self.component),
            "_paramiko",
            lambda component: fake_paramiko,
        )
        paramiko_patch.start()
        self.addCleanup(paramiko_patch.stop)
        key_patch = mock.patch.object(
            type(self.component), "_parse_key", lambda component, host: object()
        )
        key_patch.start()
        self.addCleanup(key_patch.stop)
        return fake_paramiko

    def test_strict_host_key_default(self):
        self.assertTrue(self.host.ssh_strict_host_key)
        fake_client = FakeSSHClient()
        fake_paramiko = self._fake_connect(fake_client)

        self.component._connect(self.host)

        self.assertIsInstance(fake_client.policy, fake_paramiko.RejectPolicy)
        self.assertTrue(fake_client.loaded_system_keys)
        self.assertFalse(fake_client.kwargs["allow_agent"])
        self.assertFalse(fake_client.kwargs["look_for_keys"])
        self.assertEqual(fake_client.kwargs["hostname"], "docker.example")
        self.assertEqual(fake_client.kwargs["port"], 22)
        self.assertEqual(fake_client.kwargs["username"], "deploy")

    def test_non_strict_host_key_uses_auto_add(self):
        self.host.ssh_strict_host_key = False
        fake_client = FakeSSHClient()
        fake_paramiko = self._fake_connect(fake_client)

        self.component._connect(self.host)

        self.assertIsInstance(fake_client.policy, fake_paramiko.AutoAddPolicy)

    def test_known_hosts_content_is_loaded(self):
        self.host.ssh_known_hosts = "docker.example ssh-ed25519 AAAA"
        fake_client = FakeSSHClient()
        self._fake_connect(fake_client)

        self.component._connect(self.host)

        self.assertEqual(len(fake_client.loaded_paths), 1)
        self.assertFalse(fake_client.loaded_system_keys)


class FakeSSHClient:
    def __init__(self):
        self.policy = None
        self.kwargs = None
        self.loaded_system_keys = False
        self.loaded_paths = []

    def set_missing_host_key_policy(self, policy):
        self.policy = policy

    def load_system_host_keys(self):
        self.loaded_system_keys = True

    def load_host_keys(self, path):
        self.loaded_paths.append(path)

    def connect(self, **kwargs):
        self.kwargs = kwargs

    def close(self):
        pass


class FakeParamiko:
    class SSHException(Exception):
        pass

    class RejectPolicy:
        pass

    class AutoAddPolicy:
        pass

    class RSAKey:
        pass

    class ECDSAKey:
        pass

    class Ed25519Key:
        pass

    def __init__(self, client):
        self.SSHClient = lambda: client

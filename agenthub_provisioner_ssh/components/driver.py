import io
import json
import logging
import os
import shlex
import tempfile
import uuid

import paramiko

from odoo.addons.agenthub_provisioner.contract import (
    ContainerState,
    HostProbe,
    ProvisionerError,
)
from odoo.addons.component.core import Component

_logger = logging.getLogger(__name__)


class AgenthubProvisionerDriverSsh(Component):
    _name = "agenthub.provisioner.driver.ssh"
    _inherit = "agenthub.provisioner.driver"
    _usage = "ssh"

    # ------------------------------------------------------------------
    # Connection / command execution
    # ------------------------------------------------------------------

    def _validate_host(self, host):
        if not host.ssh_host or not host.ssh_user:
            raise ProvisionerError(
                "UNREACHABLE", "SSH host and user are required."
            )
        if not host.remote_docker:
            raise ProvisionerError(
                "UNREACHABLE", "The remote docker command is required."
            )

    def _parse_key(self, host):
        if not host.ssh_private_key:
            raise ProvisionerError(
                "UNREACHABLE", "No SSH private key is configured."
            )
        password = host.ssh_key_passphrase or None
        for key_class in (
            paramiko.RSAKey,
            paramiko.ECDSAKey,
            paramiko.Ed25519Key,
        ):
            try:
                return key_class.from_private_key(
                    io.StringIO(host.ssh_private_key), password=password
                )
            except paramiko.SSHException:
                continue
        raise ProvisionerError(
            "UNREACHABLE", "The configured SSH private key cannot be parsed."
        )

    def _connect(self, host):
        self._validate_host(host)
        client = paramiko.SSHClient()
        if host.ssh_strict_host_key:
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
            if host.ssh_known_hosts:
                fd, path = tempfile.mkstemp(prefix="agenthub-known-hosts-")
                try:
                    with os.fdopen(fd, "w") as handle:
                        handle.write(host.ssh_known_hosts)
                    client.load_host_keys(path)
                finally:
                    os.unlink(path)
            else:
                client.load_system_host_keys()
        else:
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname=host.ssh_host,
                port=host.ssh_port or 22,
                username=host.ssh_user,
                pkey=self._parse_key(host),
                timeout=host.ssh_timeout or 15,
                allow_agent=False,
                look_for_keys=False,
            )
        except ProvisionerError:
            raise
        except TimeoutError as exc:
            raise ProvisionerError("TIMEOUT", "SSH connection timed out.") from exc
        except (paramiko.SSHException, OSError) as exc:
            raise ProvisionerError(
                "UNREACHABLE", "SSH connection failed: %s" % exc
            ) from exc
        return client

    @staticmethod
    def _command(argv):
        return " ".join(shlex.quote(str(argument)) for argument in argv)

    def _exec(self, host, argv, stdin=None, check=True):
        client = self._connect(host)
        try:
            command = self._command(argv)
            remote_stdin, stdout, stderr = client.exec_command(
                command, timeout=host.ssh_timeout or 15
            )
            if stdin is not None:
                remote_stdin.write(stdin)
                remote_stdin.flush()
                remote_stdin.channel.shutdown_write()
            output = stdout.read().decode("utf-8", "replace")
            error = stderr.read().decode("utf-8", "replace")
            returncode = stdout.channel.recv_exit_status()
        except TimeoutError as exc:
            raise ProvisionerError("TIMEOUT", "SSH command timed out.") from exc
        except (paramiko.SSHException, OSError) as exc:
            raise ProvisionerError(
                "UNREACHABLE", "SSH command failed: %s" % exc
            ) from exc
        finally:
            client.close()
        if check and returncode != 0:
            raise ProvisionerError(
                "SSH_COMMAND_FAILED",
                "%s failed: %s" % (argv[0], error.strip()[:500]),
            )
        return returncode, output, error

    # ------------------------------------------------------------------
    # Contract
    # ------------------------------------------------------------------

    def probe(self, host):
        try:
            docker = host.remote_docker
            _rc, output, _err = self._exec(
                host, [docker, "version", "--format", "{{.Server.Version}}"]
            )
        except ProvisionerError as exc:
            return HostProbe(False, detail=exc.detail)
        except Exception as exc:  # noqa: BLE001 - reported to the administrator
            _logger.exception("SSH probe failed for host %s", host.name)
            return HostProbe(False, detail=str(exc))
        return HostProbe(True, version=output.strip() or None)

    def apply(self, host, spec):
        info = self._inspect(host, spec.name)
        if info is not None:
            self._check_managed(info, spec)
            if (
                self._labels(info).get("agenthub.config_hash")
                == spec.config_hash
                and self._image_matches(info, spec.image)
            ):
                if (info.get("State") or {}).get("Status") != "running":
                    self._start(host, spec.name)
                refreshed = self._inspect(host, spec.name) or info
                return self._state_from_info(refreshed, spec.name)
            docker = host.remote_docker
            self._exec(host, [docker, "stop", "-t", "10", spec.name])
            self._exec(host, [docker, "rm", "-f", spec.name])

        self._ensure_image(host, spec)
        env_path = self._write_env_file(host, spec.env)
        try:
            self._create(host, spec, env_path)
            self._start(host, spec.name)
        finally:
            self._remove_env_file(host, env_path)
        refreshed = self._inspect(host, spec.name)
        if refreshed is not None:
            return self._state_from_info(refreshed, spec.name)
        return ContainerState(
            id=None,
            name=spec.name,
            status="running",
            labels=dict(spec.labels),
        )

    def stop(self, host, container_id, timeout=10):
        info = self._inspect(host, container_id)
        if info is None:
            return
        if (info.get("State") or {}).get("Status") != "running":
            return
        docker = host.remote_docker
        self._exec(host, [docker, "stop", "-t", str(timeout), container_id])

    def remove(self, host, container_id):
        if self._inspect(host, container_id) is None:
            return
        docker = host.remote_docker
        self._exec(host, [docker, "rm", "-f", container_id])

    def status(self, host, container_id):
        info = self._inspect(host, container_id)
        if info is None:
            return ContainerState(
                id=None, name=str(container_id), status="missing"
            )
        return self._state_from_info(info, str(container_id))

    def logs(self, host, container_id, tail=200):
        docker = host.remote_docker
        returncode, output, error = self._exec(
            host,
            [
                docker,
                "logs",
                "--tail",
                str(tail),
                "--timestamps",
                container_id,
            ],
            check=False,
        )
        if returncode != 0:
            return ""
        return output + error

    # ------------------------------------------------------------------
    # Docker CLI helpers
    # ------------------------------------------------------------------

    def _inspect(self, host, name):
        docker = host.remote_docker
        returncode, output, _error = self._exec(
            host, [docker, "inspect", name], check=False
        )
        if returncode != 0:
            return None
        try:
            payload = json.loads(output)
        except ValueError:
            return None
        if not payload:
            return None
        return payload[0]

    def _labels(self, info):
        return (info.get("Config") or {}).get("Labels") or {}

    def _image(self, info):
        config = info.get("Config") or {}
        return config.get("Image") or ((info.get("RepoTags") or [None])[0])

    def _image_matches(self, info, image):
        config = info.get("Config") or {}
        if config.get("Image") == image:
            return True
        return image in (info.get("RepoTags") or [])

    def _state_from_info(self, info, fallback_name):
        state = info.get("State") or {}
        name = (info.get("Name") or "").lstrip("/") or fallback_name
        health = (state.get("Health") or {}).get("Status")
        return ContainerState(
            id=info.get("Id"),
            name=name,
            status=state.get("Status") or "unknown",
            image=self._image(info),
            health=health,
            labels=self._labels(info),
        )

    def _check_managed(self, info, spec):
        labels = self._labels(info)
        name = (info.get("Name") or "").lstrip("/") or spec.name
        if labels.get("agenthub.managed") != "true":
            raise ProvisionerError(
                "CONFLICT",
                "Container '%s' exists but is not managed by Agent Hub." % name,
            )
        if labels.get("agenthub.deployment_id") != spec.labels.get(
            "agenthub.deployment_id"
        ):
            raise ProvisionerError(
                "CONFLICT",
                "Container '%s' belongs to another deployment." % name,
            )

    def _ensure_image(self, host, spec):
        docker = host.remote_docker
        returncode, _output, _error = self._exec(
            host, [docker, "image", "inspect", spec.image], check=False
        )
        if returncode == 0:
            return
        if spec.pull_policy == "never":
            raise ProvisionerError(
                "IMAGE_MISSING",
                "Image '%s' is not present and pull_policy=never." % spec.image,
            )
        try:
            self._exec(host, [docker, "pull", spec.image])
        except ProvisionerError as exc:
            raise ProvisionerError(
                "PULL_FAILED", "Could not pull image '%s': %s" % (spec.image, exc)
            ) from exc

    def _write_env_file(self, host, env):
        path = "/tmp/agenthub-provisioner-%s.env" % uuid.uuid4().hex
        content = "".join("%s=%s\n" % (key, value) for key, value in sorted(env.items()))
        try:
            self._exec(
                host,
                ["sh", "-c", "umask 077; cat > %s" % shlex.quote(path)],
                stdin=content,
            )
        except ProvisionerError as exc:
            raise ProvisionerError(
                "ENV_FILE_FAILED", "Could not write the remote env file: %s" % exc
            ) from exc
        return path

    def _remove_env_file(self, host, path):
        try:
            self._exec(host, ["rm", "-f", path], check=False)
        except ProvisionerError:
            _logger.warning("Could not remove remote env file %s", path)

    def _create(self, host, spec, env_path):
        docker = host.remote_docker
        argv = [docker, "create", "--name", spec.name]
        for key in sorted(spec.labels):
            argv += ["--label", "%s=%s" % (key, spec.labels[key])]
        argv += ["--env-file", env_path]
        if spec.network:
            argv += ["--network", spec.network]
        for name in sorted(spec.volumes):
            config = spec.volumes[name]
            argv += [
                "-v",
                "%s:%s:%s" % (name, config["bind"], config.get("mode", "rw")),
            ]
        argv += ["--restart", spec.restart_policy, spec.image]
        argv += list(spec.command)
        try:
            self._exec(host, argv)
        except ProvisionerError as exc:
            raise ProvisionerError(
                "CREATE_FAILED", "Could not create container: %s" % exc
            ) from exc

    def _start(self, host, name):
        docker = host.remote_docker
        try:
            self._exec(host, [docker, "start", name])
        except ProvisionerError as exc:
            raise ProvisionerError(
                "START_FAILED", "Could not start container: %s" % exc
            ) from exc

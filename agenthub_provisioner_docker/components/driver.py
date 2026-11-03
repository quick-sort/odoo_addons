import logging
from urllib.parse import urlsplit

import docker
from docker.errors import DockerException, ImageNotFound, NotFound

from odoo.addons.agenthub_provisioner.contract import (
    ContainerState,
    HostProbe,
    ProvisionerError,
)
from odoo.addons.component.core import Component

_logger = logging.getLogger(__name__)

LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


class AgenthubProvisionerDriverDocker(Component):
    _name = "agenthub.provisioner.driver.docker"
    _inherit = "agenthub.provisioner.driver"
    _usage = "docker"

    # ------------------------------------------------------------------
    # Client
    # ------------------------------------------------------------------

    def _validate_url(self, host):
        parts = urlsplit(host.docker_url or "")
        if parts.scheme not in ("unix", "tcp"):
            raise ProvisionerError(
                "INVALID_ENDPOINT",
                "Docker URL must use unix:// or tcp:// (got %r)."
                % (host.docker_url,),
            )
        if parts.scheme == "tcp" and not host.docker_tls:
            if (parts.hostname or "") not in LOOPBACK_HOSTS:
                raise ProvisionerError(
                    "INSECURE_ENDPOINT",
                    "A non-loopback tcp:// Docker endpoint requires TLS.",
                )

    def _client(self, host):
        self._validate_url(host)
        try:
            tls_config = None
            if host.docker_tls:
                client_cert = None
                if host.docker_tls_cert and host.docker_tls_key:
                    client_cert = (host.docker_tls_cert, host.docker_tls_key)
                tls_config = docker.tls.TLSConfig(
                    ca_cert=host.docker_tls_ca or None,
                    client_cert=client_cert,
                    verify=True,
                )
            client = docker.DockerClient(
                base_url=host.docker_url,
                timeout=host.docker_timeout or 30,
                tls=tls_config,
            )
            client.ping()
        except DockerException as exc:
            raise ProvisionerError(
                "UNREACHABLE", "Docker endpoint is unreachable: %s" % exc
            ) from exc
        return client

    # ------------------------------------------------------------------
    # Contract
    # ------------------------------------------------------------------

    def probe(self, host):
        try:
            client = self._client(host)
            version = (client.version() or {}).get("Version")
        except ProvisionerError as exc:
            return HostProbe(False, detail=exc.detail)
        except Exception as exc:  # noqa: BLE001 - reported to the administrator
            _logger.exception("Docker probe failed for host %s", host.name)
            return HostProbe(False, detail=str(exc))
        return HostProbe(True, version=version)

    def apply(self, host, spec):
        client = self._client(host)
        existing = self._find(client, spec.name)
        if existing is not None:
            self._check_managed(existing, spec)
            if (
                (existing.labels or {}).get("agenthub.config_hash")
                == spec.config_hash
                and self._image_matches(existing, spec.image)
            ):
                if existing.status != "running":
                    self._start(existing)
                return self._state(existing)
            self._stop(existing, timeout=10)
            self._remove(existing)

        self._ensure_image(client, spec)
        try:
            container = client.containers.create(
                image=spec.image,
                command=list(spec.command),
                name=spec.name,
                environment=dict(spec.env),
                volumes=dict(spec.volumes),
                labels=dict(spec.labels),
                network=spec.network or None,
                restart_policy={"Name": spec.restart_policy},
                detach=True,
            )
        except DockerException as exc:
            raise ProvisionerError(
                "CREATE_FAILED", "Could not create container: %s" % exc
            ) from exc
        self._start(container)
        return self._state(container)

    def stop(self, host, container_id, timeout=10):
        client = self._client(host)
        container = self._find(client, container_id)
        if container is None:
            return
        self._stop(container, timeout=timeout)

    def remove(self, host, container_id):
        client = self._client(host)
        container = self._find(client, container_id)
        if container is None:
            return
        self._remove(container)

    def status(self, host, container_id):
        client = self._client(host)
        container = self._find(client, container_id)
        if container is None:
            return ContainerState(
                id=None, name=str(container_id), status="missing"
            )
        return self._state(container)

    def logs(self, host, container_id, tail=200):
        client = self._client(host)
        container = self._find(client, container_id)
        if container is None:
            return ""
        try:
            output = container.logs(tail=tail, timestamps=True)
        except DockerException as exc:
            raise ProvisionerError(
                "LOGS_FAILED", "Could not read container logs: %s" % exc
            ) from exc
        if isinstance(output, bytes):
            output = output.decode("utf-8", "replace")
        return output

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find(self, client, name):
        try:
            return client.containers.get(name)
        except NotFound:
            return None

    def _check_managed(self, container, spec):
        labels = container.labels or {}
        if labels.get("agenthub.managed") != "true":
            raise ProvisionerError(
                "CONFLICT",
                "Container '%s' exists but is not managed by Agent Hub."
                % container.name,
            )
        if labels.get("agenthub.deployment_id") != spec.labels.get(
            "agenthub.deployment_id"
        ):
            raise ProvisionerError(
                "CONFLICT",
                "Container '%s' belongs to another deployment." % container.name,
            )

    def _image_matches(self, container, image):
        tags = getattr(getattr(container, "image", None), "tags", None) or []
        if image in tags:
            return True
        attrs = getattr(container, "attrs", None) or {}
        return (attrs.get("Config") or {}).get("Image") == image

    def _ensure_image(self, client, spec):
        if spec.pull_policy == "never":
            try:
                client.images.get(spec.image)
            except ImageNotFound as exc:
                raise ProvisionerError(
                    "IMAGE_MISSING",
                    "Image '%s' is not present and pull_policy=never."
                    % spec.image,
                ) from exc
            return
        if spec.pull_policy == "always":
            self._pull(client, spec.image)
            return
        try:
            client.images.get(spec.image)
        except ImageNotFound:
            self._pull(client, spec.image)

    def _pull(self, client, image):
        try:
            client.images.pull(image)
        except DockerException as exc:
            raise ProvisionerError(
                "PULL_FAILED", "Could not pull image '%s': %s" % (image, exc)
            ) from exc

    def _start(self, container):
        try:
            container.start()
        except DockerException as exc:
            raise ProvisionerError(
                "START_FAILED", "Could not start container: %s" % exc
            ) from exc

    def _stop(self, container, timeout=10):
        try:
            if container.status != "running":
                return
            container.stop(timeout=timeout)
        except DockerException as exc:
            raise ProvisionerError(
                "STOP_FAILED", "Could not stop container: %s" % exc
            ) from exc

    def _remove(self, container):
        try:
            container.remove(force=True)
        except NotFound:
            return
        except DockerException as exc:
            raise ProvisionerError(
                "REMOVE_FAILED", "Could not remove container: %s" % exc
            ) from exc

    def _state(self, container):
        attrs = getattr(container, "attrs", None) or {}
        state = attrs.get("State") or {}
        tags = getattr(getattr(container, "image", None), "tags", None) or []
        image = tags[0] if tags else (attrs.get("Config") or {}).get("Image")
        health = (state.get("Health") or {}).get("Status")
        return ContainerState(
            id=container.id,
            name=container.name,
            status=container.status or state.get("Status") or "unknown",
            image=image,
            health=health,
            labels=dict(container.labels or {}),
        )

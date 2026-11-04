"""Driver-neutral container contracts for :mod:`agenthub_provisioner`."""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class ContainerSpec:
    """Everything a driver needs to create and start one agent-box container."""

    name: str
    image: str
    command: tuple[str, ...]
    env: Mapping[str, str]
    volumes: Mapping[str, Mapping[str, str]]
    labels: Mapping[str, str]
    config_hash: str
    network: str | None = None
    restart_policy: str = "unless-stopped"
    pull_policy: str = "missing"


@dataclass(frozen=True)
class ContainerState:
    """Observed state of a container; ``status="missing"`` when absent."""

    id: str | None
    name: str
    status: str
    image: str | None = None
    health: str | None = None
    labels: Mapping[str, str] | None = None
    error: str | None = None


@dataclass(frozen=True)
class HostProbe:
    """Result of a connectivity probe against a provisioner host."""

    ok: bool
    version: str | None = None
    detail: str | None = None


class ProvisionerError(Exception):
    """Driver boundary error.

    ``code`` is stable and safe to match on; ``detail`` is shown to the
    administrator after the core has masked known secrets.
    """

    def __init__(self, code, detail):
        super().__init__(detail)
        self.code = code
        self.detail = detail

    def __str__(self):
        return f"{self.code}: {self.detail}"

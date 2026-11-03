"""Abstract driver contract for ``agenthub.provisioner.host``.

Concrete drivers live in their own addons and ``_inherit`` this component,
setting ``_usage`` to the ``driver_type`` Selection value they also contribute
via ``selection_add``. Methods take the host record explicitly so the driver
reads configuration from its argument and stays testable without a database.
"""

from odoo.addons.component.core import AbstractComponent


class AgenthubProvisionerDriver(AbstractComponent):
    """Container lifecycle contract for a provisioner host."""

    _name = "agenthub.provisioner.driver"
    _collection = "agenthub.provisioner.host"

    def probe(self, host):
        """Return a :class:`~odoo.addons.agenthub_provisioner.contract.HostProbe`."""
        raise NotImplementedError(
            f"Driver '{self._usage}' ({self._name}) does not implement probe()"
        )

    def apply(self, host, spec):
        """Idempotently ensure a container matches ``spec`` and is running.

        Returns a :class:`~odoo.addons.agenthub_provisioner.contract.ContainerState`.
        """
        raise NotImplementedError(
            f"Driver '{self._usage}' ({self._name}) does not implement apply()"
        )

    def stop(self, host, container_id, timeout=10):
        """Stop a managed container; no-op when absent or already stopped."""
        raise NotImplementedError(
            f"Driver '{self._usage}' ({self._name}) does not implement stop()"
        )

    def remove(self, host, container_id):
        """Stop and delete a managed container; no-op when absent."""
        raise NotImplementedError(
            f"Driver '{self._usage}' ({self._name}) does not implement remove()"
        )

    def status(self, host, container_id):
        """Return the current :class:`ContainerState`; ``status="missing"``."""
        raise NotImplementedError(
            f"Driver '{self._usage}' ({self._name}) does not implement status()"
        )

    def logs(self, host, container_id, tail=200):
        """Return the last ``tail`` log lines as text."""
        raise NotImplementedError(
            f"Driver '{self._usage}' ({self._name}) does not implement logs()"
        )

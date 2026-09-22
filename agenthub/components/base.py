"""Abstract component contracts for the agenthub extension points.

Every concrete channel/agent addon registers one component that ``_inherit``s
one of these bases and sets a unique ``_usage`` equal to the ``channel_type`` /
``agent_type`` Selection value it also contributes via ``selection_add``.

Resolution is by usage against the model's own collection
(``work.component(usage=self.channel_type)``), so the abstract base must set
``_collection`` to the model name — without it the component would match every
collection in the database.

Methods take the ``agenthub.channel`` / ``agenthub.agent`` record as their first
argument (the same convention as ``llm.provider.adapter``), so a concrete
adapter reads configuration from the argument rather than ``self.collection``
and stays unit-testable without a database.
"""

from odoo.addons.component.core import AbstractComponent


class AgenthubChannelAdapter(AbstractComponent):
    """Transport contract for ``agenthub.channel``."""

    _name = "agenthub.channel.adapter"
    _collection = "agenthub.channel"

    def send(self, channel, message):
        """Deliver an outbound ``mail.message`` to the channel's peer."""
        raise NotImplementedError(
            f"Channel adapter '{self._usage}' ({self._name}) does not "
            "implement send()"
        )


class AgenthubAgentAdapter(AbstractComponent):
    """Reply contract for ``agenthub.agent``."""

    _name = "agenthub.agent.adapter"
    _collection = "agenthub.agent"

    def reply(self, agent, message):
        """Produce a reply for an inbound ``mail.message``."""
        raise NotImplementedError(
            f"Agent adapter '{self._usage}' ({self._name}) does not "
            "implement reply()"
        )

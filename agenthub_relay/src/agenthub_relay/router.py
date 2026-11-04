"""Config-driven routing for external channels and Odoo-originated events."""

from __future__ import annotations

from urllib.parse import quote

from .config import ConfigSnapshot
from .envelope import Route


class RoutingError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class Router:
    def __init__(self, snapshot: ConfigSnapshot):
        self.snapshot = snapshot

    def resolve_external(self, channel_id: int, peer_ref: str) -> Route:
        identity_user = self.snapshot.identities.get((int(channel_id), peer_ref))
        if identity_user is None:
            raise RoutingError(
                "IDENTITY_NOT_FOUND",
                f"No identity for channel={channel_id} peer={peer_ref!r}",
            )
        agent_id = self.snapshot.bindings.get((identity_user, int(channel_id)))
        if agent_id is None:
            raise RoutingError(
                "BINDING_NOT_FOUND",
                f"No binding for user={identity_user} channel={channel_id}",
            )
        agent = self.snapshot.agents.get(agent_id)
        if agent is None or not agent.active:
            raise RoutingError(
                "AGENT_INACTIVE", f"Agent {agent_id} is missing or inactive"
            )
        thread_key = (
            f"agenthub:channel:{channel_id}:peer:{quote(peer_ref, safe='')}"
            f":agent:{agent_id}"
        )
        return Route(
            agent_id=agent_id,
            channel_id=channel_id,
            thread_key=thread_key,
            peer_ref=peer_ref,
            user_id=identity_user,
        )

    def resolve_odoo(self, route: Route) -> Route:
        if route.agent_id is None or not route.thread_key:
            raise RoutingError(
                "INVALID_ROUTE", "Odoo events require agent_id and thread_key"
            )
        agent = self.snapshot.agents.get(int(route.agent_id))
        if agent is not None and not agent.active:
            raise RoutingError(
                "AGENT_INACTIVE", f"Agent {route.agent_id} is inactive"
            )
        return route

    def resolve_command(
        self, agent_id: int, thread_key: str | None = None
    ) -> Route:
        agent = self.snapshot.agents.get(int(agent_id))
        if agent is None or not agent.active:
            raise RoutingError(
                "AGENT_INACTIVE", f"Agent {agent_id} is missing or inactive"
            )
        return Route(
            agent_id=int(agent_id),
            thread_key=thread_key,
            reply_mode="thread" if thread_key else "none",
        )

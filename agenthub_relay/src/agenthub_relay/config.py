"""Relay configuration and Odoo config snapshot."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AgentConfig:
    agent_id: int
    token_hash: str
    active: bool = True


@dataclass(frozen=True)
class ChannelConfig:
    channel_id: int
    type: str
    bot_id: str = ""
    secret: str = ""
    active: bool = True


@dataclass
class ConfigSnapshot:
    """Routing cache pulled from Odoo.

    ``identities`` maps ``(channel_id, peer_ref) -> user_id``.
    ``bindings`` maps ``(user_id, channel_id) -> agent_id``.
    """

    version: int = 0
    agents: dict[int, AgentConfig] = field(default_factory=dict)
    channels: dict[int, ChannelConfig] = field(default_factory=dict)
    identities: dict[tuple[int, str], int] = field(default_factory=dict)
    bindings: dict[tuple[int, int], int] = field(default_factory=dict)

    def find_channel(self, bot_id: str) -> ChannelConfig | None:
        for channel in self.channels.values():
            if channel.active and channel.bot_id and channel.bot_id == bot_id:
                return channel
        return None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConfigSnapshot":
        agents = {
            int(item["id"]): AgentConfig(
                agent_id=int(item["id"]),
                token_hash=item["token_hash"],
                active=bool(item.get("active", True)),
            )
            for item in data.get("agents", [])
        }
        channels = {
            int(item["id"]): ChannelConfig(
                channel_id=int(item["id"]),
                type=str(item.get("type") or ""),
                bot_id=str(item.get("bot_id") or ""),
                secret=str(item.get("secret") or ""),
                active=bool(item.get("active", True)),
            )
            for item in data.get("channels", [])
        }
        identities = {
            (int(item["channel_id"]), str(item["peer_ref"])): int(
                item["user_id"]
            )
            for item in data.get("identities", [])
        }
        bindings = {
            (int(item["user_id"]), int(item["channel_id"])): int(
                item["agent_id"]
            )
            for item in data.get("bindings", [])
        }
        return cls(
            version=int(data.get("version", 0)),
            agents=agents,
            channels=channels,
            identities=identities,
            bindings=bindings,
        )

    def apply(self, other: "ConfigSnapshot") -> None:
        """Replace the cache atomically (caller holds a lock if needed)."""
        self.version = other.version
        self.agents = dict(other.agents)
        self.channels = dict(other.channels)
        self.identities = dict(other.identities)
        self.bindings = dict(other.bindings)


def load_snapshot(path: str | Path) -> ConfigSnapshot:
    with Path(path).open("r", encoding="utf-8") as handle:
        return ConfigSnapshot.from_dict(json.load(handle))


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8090
    publish_secret: str = "dev-secret"
    recorder_token: str = "dev-recorder"
    lease_seconds: float = 60.0
    max_attempts: int = 5
    timestamp_window: int = 300
    config_file: str | None = None
    odoo_config_url: str = ""
    odoo_config_token: str = ""
    config_poll_seconds: float = 15.0
    redis_url: str = ""
    wecom_lease_seconds: float = 90.0
    wecom_poll_seconds: float = 0.5
    wecom_request_ttl_seconds: int = 86400

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            host=os.environ.get("AGENTHUB_RELAY_HOST", "127.0.0.1"),
            port=int(os.environ.get("AGENTHUB_RELAY_PORT", "8090")),
            publish_secret=os.environ.get(
                "AGENTHUB_PUBLISH_SECRET", "dev-secret"
            ),
            recorder_token=os.environ.get(
                "AGENTHUB_RECORDER_TOKEN", "dev-recorder"
            ),
            lease_seconds=float(
                os.environ.get("AGENTHUB_LEASE_SECONDS", "60")
            ),
            max_attempts=int(os.environ.get("AGENTHUB_MAX_ATTEMPTS", "5")),
            timestamp_window=int(
                os.environ.get("AGENTHUB_TIMESTAMP_WINDOW", "300")
            ),
            config_file=os.environ.get("AGENTHUB_CONFIG_FILE") or None,
            odoo_config_url=os.environ.get("AGENTHUB_ODOO_CONFIG_URL", ""),
            odoo_config_token=os.environ.get(
                "AGENTHUB_ODOO_CONFIG_TOKEN", ""
            ),
            config_poll_seconds=float(
                os.environ.get("AGENTHUB_CONFIG_POLL_SECONDS", "15")
            ),
            redis_url=os.environ.get("AGENTHUB_REDIS_URL", ""),
            wecom_lease_seconds=float(
                os.environ.get("AGENTHUB_WECOM_LEASE_SECONDS", "90")
            ),
            wecom_poll_seconds=float(
                os.environ.get("AGENTHUB_WECOM_POLL_SECONDS", "0.5")
            ),
            wecom_request_ttl_seconds=int(
                os.environ.get("AGENTHUB_WECOM_REQUEST_TTL_SECONDS", "86400")
            ),
        )

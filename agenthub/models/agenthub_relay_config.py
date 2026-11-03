import hashlib
import json

from odoo import api, models


class AgenthubRelayConfig(models.AbstractModel):
    """Versioned snapshot the relay pulls to refresh its routing cache."""

    _name = "agenthub.relay.config"
    _description = "Agent Hub Relay Config Snapshot"

    @api.model
    def _snapshot(self):
        agents = self.env["agenthub.agent"].search(
            [("active", "=", True), ("token_hash", "!=", False)]
        )
        channels = self.env["agenthub.channel"].search([])
        identities = self.env["agenthub.identity"].search(
            [("active", "=", True)]
        )
        bindings = self.env["agenthub.binding"].search(
            [("active", "=", True)]
        )
        payload = {
            "agents": [
                {
                    "id": agent.id,
                    "token_hash": agent.token_hash,
                    "active": agent.active,
                }
                for agent in agents
            ],
            "channels": [self._channel_payload(channel) for channel in channels],
            "identities": [
                {
                    "channel_id": identity.channel_id.id,
                    "peer_ref": identity.peer_ref,
                    "user_id": identity.user_id.id,
                }
                for identity in identities
            ],
            "bindings": [
                {
                    "user_id": binding.user_id.id,
                    "channel_id": binding.channel_id.id,
                    "agent_id": binding.agent_id.id,
                }
                for binding in bindings
            ],
        }
        digest = hashlib.sha1(
            json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        payload["version"] = int(digest[:12], 16)
        return payload

    @api.model
    def _channel_payload(self, channel):
        item = {
            "id": channel.id,
            "type": channel.channel_type,
            "active": channel.active,
        }
        # Channel addons (e.g. agenthub_wecom) own these fields; core must not
        # depend on them. Transport is expected to be TLS/mTLS.
        if "bot_id" in channel._fields:
            item["bot_id"] = channel.bot_id or ""
        if "secret" in channel._fields:
            item["secret"] = channel.secret or ""
        return item

"""Pull the versioned routing snapshot from Odoo."""

from __future__ import annotations

import asyncio
import logging

import httpx

from .config import ConfigSnapshot
from .protocol import AgentDirectory
from .router import Router

log = logging.getLogger(__name__)


async def sync_once(app, client: httpx.AsyncClient) -> bool:
    settings = app.state.settings
    url = settings.odoo_config_url.rstrip("/") + "/agenthub/relay/config"
    response = await client.get(
        url,
        params={"version": app.state.snapshot.version},
        headers={"X-AgentHub-Config-Token": settings.odoo_config_token},
    )
    if response.status_code != 200:
        log.warning("relay config sync: HTTP %s", response.status_code)
        return False
    data = response.json()
    remote_version = int(data.get("version", 0))
    if remote_version == app.state.snapshot.version:
        return False
    snapshot = ConfigSnapshot.from_dict(data)
    app.state.snapshot.apply(snapshot)
    app.state.directory = AgentDirectory(snapshot.agents)
    app.state.router = Router(snapshot)
    log.info("relay config updated to version %s", remote_version)
    return True


async def config_sync_loop(app) -> None:
    settings = app.state.settings
    async with httpx.AsyncClient(timeout=10.0) as client:
        while True:
            try:
                await sync_once(app, client)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - keep the loop alive
                log.exception("relay config sync failed")
            await asyncio.sleep(settings.config_poll_seconds)

"""Home Assistant core access from inside the app: release and restore the integration.

A serial port is exclusive, so while the elkm1 integration holds the panel's
RS-232 port the programmer cannot open it. Before a session the app disables
the integration's config entries, which closes the port; after the session
it re-enables them, which reconnects and runs the integration's full sync.
The entry ids are written to a marker file first so a crash between the two
calls is repaired on the next start. Core exposes entry listing over REST
(``/api/config/config_entries/entry?domain=``) and disabling only over the
WebSocket API (``config_entries/disable``); both are reached through the
Supervisor's core proxy with the Supervisor token.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx
import websockets

_LOGGER = logging.getLogger(__name__)

SUPERVISOR_HTTP = "http://supervisor"
SUPERVISOR_WS = "ws://supervisor/core/websocket"
DISABLED_BY_USER = "user"


class HomeAssistantError(Exception):
    pass


class HomeAssistant:
    """The two core calls the app needs, over the Supervisor proxy."""

    def __init__(
        self, token: str, http_base: str = SUPERVISOR_HTTP, ws_url: str = SUPERVISOR_WS
    ) -> None:
        self._token = token
        self._http_base = http_base.rstrip("/")
        self._ws_url = ws_url
        self._transport: httpx.AsyncBaseTransport | None = None

    def use_transport(self, transport: httpx.AsyncBaseTransport) -> None:
        """Tests inject a transport; production uses the network."""
        self._transport = transport

    async def config_entries(self, domain: str) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=15, transport=self._transport) as client:
            r = await client.get(
                f"{self._http_base}/core/api/config/config_entries/entry",
                params={"domain": domain},
                headers={"Authorization": f"Bearer {self._token}"},
            )
        if r.status_code != 200:
            raise HomeAssistantError(f"listing config entries failed with HTTP {r.status_code}")
        data = r.json()
        if not isinstance(data, list):
            raise HomeAssistantError("unexpected config entry listing")
        return [e for e in data if isinstance(e, dict)]

    async def set_entry_disabled(self, entry_id: str, disabled: bool) -> bool:
        """Disable or enable one entry; return whether core requires a restart."""
        async with websockets.connect(self._ws_url, open_timeout=15) as ws:
            first = json.loads(await ws.recv())
            if first.get("type") != "auth_required":
                raise HomeAssistantError("core did not ask for authentication")
            await ws.send(json.dumps({"type": "auth", "access_token": self._token}))
            auth = json.loads(await ws.recv())
            if auth.get("type") != "auth_ok":
                raise HomeAssistantError("core refused the Supervisor token")
            await ws.send(
                json.dumps(
                    {
                        "id": 1,
                        "type": "config_entries/disable",
                        "entry_id": entry_id,
                        "disabled_by": DISABLED_BY_USER if disabled else None,
                    }
                )
            )
            reply = json.loads(await ws.recv())
        if not reply.get("success"):
            error = reply.get("error", {})
            raise HomeAssistantError(
                f"core refused to change entry {entry_id}: {error.get('message', 'unknown error')}"
            )
        return bool(reply.get("result", {}).get("require_restart"))


class IntegrationRelease:
    """Disable the integration's entries for a session and put them back afterwards."""

    def __init__(self, ha: HomeAssistant, marker: Path, domain: str = "elkm1") -> None:
        self._ha = ha
        self._marker = marker
        self._domain = domain

    def pending(self) -> list[str]:
        """Entry ids a previous run disabled and did not restore."""
        if not self._marker.is_file():
            return []
        try:
            data = json.loads(self._marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        ids = data.get("entry_ids", [])
        return [str(i) for i in ids] if isinstance(ids, list) else []

    async def release(self) -> list[str]:
        """Disable every enabled entry of the domain; return the ids disabled."""
        entries = await self._ha.config_entries(self._domain)
        targets = [
            str(e["entry_id"]) for e in entries if e.get("entry_id") and not e.get("disabled_by")
        ]
        if not targets:
            return []
        self._marker.parent.mkdir(parents=True, exist_ok=True)
        self._marker.write_text(json.dumps({"entry_ids": targets}), encoding="utf-8")
        done: list[str] = []
        try:
            for entry_id in targets:
                await self._ha.set_entry_disabled(entry_id, True)
                done.append(entry_id)
        except HomeAssistantError:
            # Put back what was disabled so far, then let the caller report.
            for entry_id in done:
                try:
                    await self._ha.set_entry_disabled(entry_id, False)
                except HomeAssistantError:
                    _LOGGER.error("could not re-enable %s after a failed release", entry_id)
            self._marker.unlink(missing_ok=True)
            raise
        return done

    async def restore(self) -> list[str]:
        """Re-enable the entries in the marker; return the ids restored."""
        ids = self.pending()
        failed: list[str] = []
        for entry_id in ids:
            try:
                await self._ha.set_entry_disabled(entry_id, False)
            except HomeAssistantError as err:
                _LOGGER.error("could not re-enable %s: %s", entry_id, err)
                failed.append(entry_id)
        if failed:
            self._marker.write_text(json.dumps({"entry_ids": failed}), encoding="utf-8")
            raise HomeAssistantError(f"integration entries still disabled: {', '.join(failed)}")
        self._marker.unlink(missing_ok=True)
        return ids

"""Release and restore of the integration's config entries against a fake core."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
import websockets

from elk_programmer.hass import HomeAssistant, HomeAssistantError, IntegrationRelease


class FakeCore:
    """REST listing plus a WebSocket that records disable calls."""

    def __init__(self, entries: list[dict[str, object]], token: str = "tok") -> None:
        self.entries = entries
        self.token = token
        self.calls: list[tuple[str, object]] = []
        self.refuse: set[str] = set()

    async def handle_http(self, request: httpx.Request) -> httpx.Response:
        if request.headers.get("Authorization") != f"Bearer {self.token}":
            return httpx.Response(401)
        assert request.url.path == "/core/api/config/config_entries/entry"
        domain = request.url.params.get("domain")
        return httpx.Response(200, json=[e for e in self.entries if e["domain"] == domain])

    async def handle_ws(self, ws: websockets.ServerConnection) -> None:
        await ws.send(json.dumps({"type": "auth_required"}))
        auth = json.loads(await ws.recv())
        if auth.get("access_token") != self.token:
            await ws.send(json.dumps({"type": "auth_invalid"}))
            return
        await ws.send(json.dumps({"type": "auth_ok"}))
        msg = json.loads(await ws.recv())
        assert msg["type"] == "config_entries/disable"
        self.calls.append((msg["entry_id"], msg["disabled_by"]))
        if msg["entry_id"] in self.refuse:
            await ws.send(
                json.dumps({"id": msg["id"], "success": False, "error": {"message": "nope"}})
            )
            return
        for e in self.entries:
            if e["entry_id"] == msg["entry_id"]:
                e["disabled_by"] = msg["disabled_by"]
        await ws.send(
            json.dumps({"id": msg["id"], "success": True, "result": {"require_restart": False}})
        )


@pytest.fixture
async def core() -> tuple[FakeCore, HomeAssistant]:
    fake = FakeCore(
        [
            {"entry_id": "e1", "domain": "elkm1", "disabled_by": None, "title": "Panel"},
            {"entry_id": "e2", "domain": "elkm1", "disabled_by": "user", "title": "Old"},
            {"entry_id": "x1", "domain": "other", "disabled_by": None, "title": "Other"},
        ]
    )
    server = await websockets.serve(fake.handle_ws, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    ha = HomeAssistant("tok", http_base="http://supervisor", ws_url=f"ws://127.0.0.1:{port}")
    ha.use_transport(httpx.MockTransport(fake.handle_http))
    try:
        yield fake, ha
    finally:
        server.close()
        await server.wait_closed()


async def test_release_disables_only_enabled_entries_and_restore_puts_them_back(
    core: tuple[FakeCore, HomeAssistant], tmp_path: Path
) -> None:
    fake, ha = core
    rel = IntegrationRelease(ha, tmp_path / "session.json")
    assert rel.pending() == []
    assert await rel.release() == ["e1"]
    assert fake.calls == [("e1", "user")]
    assert rel.pending() == ["e1"]
    assert await rel.restore() == ["e1"]
    assert fake.calls[-1] == ("e1", None)
    assert rel.pending() == []
    assert not (tmp_path / "session.json").exists()


async def test_failed_release_rolls_back_and_raises(
    core: tuple[FakeCore, HomeAssistant], tmp_path: Path
) -> None:
    fake, ha = core
    fake.entries.insert(1, {"entry_id": "e0", "domain": "elkm1", "disabled_by": None})
    fake.refuse.add("e0")
    rel = IntegrationRelease(ha, tmp_path / "session.json")
    with pytest.raises(HomeAssistantError):
        await rel.release()
    # e1 was disabled first, then re-enabled by the rollback; e0 was refused.
    assert fake.calls == [("e1", "user"), ("e0", "user"), ("e1", None)]
    assert rel.pending() == []


async def test_bad_token_and_restart_flag(core: tuple[FakeCore, HomeAssistant]) -> None:
    fake, ha = core
    bad = HomeAssistant("wrong", http_base="http://supervisor", ws_url=ha._ws_url)
    bad.use_transport(httpx.MockTransport(fake.handle_http))
    with pytest.raises(HomeAssistantError):
        await bad.config_entries("elkm1")
    with pytest.raises(HomeAssistantError):
        await bad.set_entry_disabled("e1", True)
    assert await ha.set_entry_disabled("e1", True) is False
    await asyncio.sleep(0)

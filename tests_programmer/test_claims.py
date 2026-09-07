"""The app announces its sessions to the integration, in the right order, on every path."""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from elk_programmer import security
from elk_programmer.hass import HomeAssistant, HomeAssistantError


class RecordingCore:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail = False
        self.ingested = 0

    async def handle(self, request: httpx.Request) -> httpx.Response:
        if request.headers.get("Authorization") != "Bearer tok":
            return httpx.Response(401)
        import json

        body = json.loads(request.content or b"{}")
        if request.url.path.endswith("/ha_soc/ingest_audit"):
            n = len(body["records"])
            self.ingested += n
            return httpx.Response(
                200,
                json={
                    "service_response": {
                        "accepted": n,
                        "last_seq": body["records"][-1]["seq"],
                        "rejected": None,
                    }
                },
            )
        if self.fail:
            return httpx.Response(500)
        self.calls.append((request.url.path, body))
        return httpx.Response(200, json=[])


async def test_call_service_posts_to_the_core_proxy() -> None:
    core = RecordingCore()
    ha = HomeAssistant("tok", http_base="http://supervisor")
    ha.use_transport(httpx.MockTransport(core.handle))
    await ha.call_service("elkm1", "programming_session_start", {"source": "elk_programmer"})
    assert core.calls == [
        ("/core/api/services/elkm1/programming_session_start", {"source": "elk_programmer"})
    ]
    core.fail = True
    with pytest.raises(HomeAssistantError):
        await ha.call_service("elkm1", "programming_session_end", {})


@pytest.fixture
def app_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    monkeypatch.setenv("ELK_PROGRAMMER_MODE", "app")
    monkeypatch.setenv("ELK_PROGRAMMER_DATA", str(tmp_path))
    monkeypatch.setenv("ELK_PROGRAMMER_ALLOWED_USERS", "alice-id")
    monkeypatch.setenv("ELK_PROGRAMMER_IDLE_MINUTES", "0")
    monkeypatch.setenv("ELK_PROGRAMMER_READ_ONLY", "false")
    monkeypatch.setenv("ELK_PROGRAMMER_RELEASE_INTEGRATION", "false")
    monkeypatch.setenv("ELK_PROGRAMMER_FORWARD_AUDIT", "true")
    monkeypatch.setenv("SUPERVISOR_TOKEN", "tok")
    monkeypatch.setattr(security, "FAILURE_DELAY", 0.0)
    monkeypatch.setattr(security, "SCRYPT_N", 2**8)
    from elk_programmer.web import app as web_app

    module = importlib.reload(web_app)
    core = RecordingCore()
    assert module.state.hass is not None
    module.state.hass.use_transport(httpx.MockTransport(core.handle))
    with TestClient(module.app) as client:
        yield module, client, core


def test_setup_on_a_worker_thread_forwards_the_audit_record(app_env: Any) -> None:
    """Passphrase setup is a synchronous endpoint; the forwarding hook must not need the loop."""
    module, client, core = app_env
    hdr = {"X-Remote-User-Id": "alice-id", "X-Remote-User-Name": "Alice"}
    r = client.post("/api/auth/setup", json={"passphrase": "correct horse battery"}, headers=hdr)
    assert r.status_code == 200, r.text
    status = client.get("/api/audit/forwarding", headers=hdr).json()
    assert status["enabled"] is True
    # The push ran on the loop and HA SOC acknowledged the setup and login records.
    import time

    for _ in range(50):
        if core.ingested >= 2:
            break
        time.sleep(0.05)
    assert core.ingested >= 2
    assert module.state.soc is not None and module.state.soc.last_seq >= 2


def test_failed_transport_still_claims_then_ends(app_env: Any) -> None:
    _module, client, core = app_env
    hdr = {"X-Remote-User-Id": "alice-id", "X-Remote-User-Name": "Alice"}
    client.post("/api/auth/setup", json={"passphrase": "correct horse battery"}, headers=hdr)
    r = client.post(
        "/api/panel/connect",
        json={
            "method": "serial",
            "serial_port": "\\\\.\\COM254",
            "baud": 115200,
            "rp_code": "246801",
        },
        headers=hdr,
    )
    assert r.status_code == 400
    paths = [p for p, _ in core.calls]
    assert paths == [
        "/core/api/services/elkm1/programming_session_start",
        "/core/api/services/elkm1/programming_session_end",
    ]
    assert core.calls[0][1] == {
        "source": "elk_programmer",
        "user": "alice-id",
        "purpose": "programming",
    }
    events = [e["event"] for e in client.get("/api/audit", headers=hdr).json()["entries"]]
    assert "session_claimed" in events and "session_claim_ended" in events


def test_claim_failure_is_audited_and_does_not_block(app_env: Any) -> None:
    _module, client, core = app_env
    hdr = {"X-Remote-User-Id": "alice-id"}
    client.post("/api/auth/setup", json={"passphrase": "correct horse battery"}, headers=hdr)
    core.fail = True
    r = client.post(
        "/api/panel/connect",
        json={"method": "serial", "serial_port": "\\\\.\\COM254", "rp_code": "246801"},
        headers=hdr,
    )
    # The claim failed, the transport failed; both are recorded and the reply is the transport's.
    assert r.status_code == 400
    events = [e["event"] for e in client.get("/api/audit", headers=hdr).json()["entries"]]
    assert "session_claim_failed" in events
    assert "session_claim_end_failed" in events

"""App mode through the HTTP surface: allow-list, passphrase, sessions, writes."""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from elk_programmer import security


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("ELK_PROGRAMMER_MODE", "app")
    monkeypatch.setenv("ELK_PROGRAMMER_DATA", str(tmp_path))
    monkeypatch.setenv("ELK_PROGRAMMER_ALLOWED_USERS", "alice-id, bob-id")
    monkeypatch.setenv("ELK_PROGRAMMER_IDLE_MINUTES", "0")
    monkeypatch.setenv("ELK_PROGRAMMER_READ_ONLY", "false")
    monkeypatch.setattr(security, "FAILURE_DELAY", 0.0)
    monkeypatch.setattr(security, "SCRYPT_N", 2**8)
    from elk_programmer.web import app as web_app

    module = importlib.reload(web_app)
    with TestClient(module.app) as c:
        yield c


def hdr(user: str, name: str = "") -> dict[str, str]:
    return {
        "X-Remote-User-Id": user,
        "X-Remote-User-Name": name or user,
    }


def test_unlisted_user_is_refused_everywhere(client: TestClient) -> None:
    assert client.get("/", headers=hdr("mallory")).status_code == 403
    assert client.get("/api/auth/status", headers=hdr("mallory")).status_code == 403
    assert client.get("/api/specs", headers=hdr("mallory")).status_code == 403
    assert client.get("/api/specs").status_code == 403


def test_setup_then_login_then_api(client: TestClient) -> None:
    status = client.get("/api/auth/status", headers=hdr("alice-id", "Alice")).json()
    assert status["mode"] == "app" and not status["set_up"] and not status["logged_in"]
    assert client.get("/api/specs", headers=hdr("alice-id")).status_code == 401
    r = client.post(
        "/api/auth/login", json={"passphrase": "whatever you like"}, headers=hdr("alice-id")
    )
    assert r.status_code == 409
    r = client.post(
        "/api/auth/setup",
        json={"passphrase": "correct horse battery"},
        headers=hdr("alice-id", "Alice"),
    )
    assert r.status_code == 200
    assert client.cookies.get("elk_session")
    assert client.get("/api/specs", headers=hdr("alice-id")).status_code == 200
    # Second setup is refused; the cookie does not transfer to another user.
    assert (
        client.post(
            "/api/auth/setup", json={"passphrase": "another passphrase"}, headers=hdr("bob-id")
        ).status_code
        == 400
    )
    assert client.get("/api/specs", headers=hdr("bob-id")).status_code == 401
    status = client.get("/api/auth/status", headers=hdr("alice-id")).json()
    assert status["logged_in"] and not status["can_write"] and status["audit_intact"]


def test_writes_need_step_up_and_read_only_wins(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client.post(
        "/api/auth/setup", json={"passphrase": "correct horse battery"}, headers=hdr("alice-id")
    )
    body = {"spec": "area", "number": 1, "dry_run": False}
    assert client.post("/api/panel/write", json=body, headers=hdr("alice-id")).status_code == 403
    assert (
        client.post(
            "/api/panel/write", json={**body, "dry_run": True}, headers=hdr("alice-id")
        ).status_code
        == 200
    )
    r = client.post(
        "/api/auth/step_up", json={"passphrase": "wrong passphrase!"}, headers=hdr("alice-id")
    )
    assert r.status_code == 401
    r = client.post(
        "/api/auth/step_up", json={"passphrase": "correct horse battery"}, headers=hdr("alice-id")
    )
    assert r.status_code == 200
    # Stepped up but no panel session: the write is refused for that reason, not for auth.
    assert client.post("/api/panel/write", json=body, headers=hdr("alice-id")).status_code == 409
    from elk_programmer.web import app as web_app

    monkeypatch.setattr(web_app.settings, "read_only", True)
    assert client.post("/api/panel/write", json=body, headers=hdr("alice-id")).status_code == 403
    audit = client.get("/api/audit", headers=hdr("alice-id")).json()
    assert audit["intact"]
    assert [e["event"] for e in audit["entries"]][:4] == [
        "setup",
        "login",
        "login_failed",
        "step_up",
    ]


def test_lockout_over_http(client: TestClient) -> None:
    client.post(
        "/api/auth/setup", json={"passphrase": "correct horse battery"}, headers=hdr("alice-id")
    )
    client.post("/api/auth/logout", headers=hdr("alice-id"))
    for _ in range(security.LOCKOUT_FAILURES - 1):
        assert (
            client.post(
                "/api/auth/login", json={"passphrase": "nope nope nope"}, headers=hdr("bob-id")
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/api/auth/login", json={"passphrase": "nope nope nope"}, headers=hdr("bob-id")
        ).status_code
        == 429
    )
    assert (
        client.post(
            "/api/auth/login", json={"passphrase": "correct horse battery"}, headers=hdr("alice-id")
        ).status_code
        == 429
    )

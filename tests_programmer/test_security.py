"""Passphrase, sessions, lockout, and the audit chain."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from elk_programmer import security
from elk_programmer.security import (
    AccessControl,
    AuditLog,
    AuthError,
    BadPassphrase,
    LockedOut,
    NotSetUp,
)


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture(autouse=True)
def no_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(security, "FAILURE_DELAY", 0.0)
    monkeypatch.setattr(security, "SCRYPT_N", 2**8)


@pytest.fixture
def ac(tmp_path: Path) -> AccessControl:
    control = AccessControl(tmp_path, frozenset({"u1", "u2"}))
    control.clock = Clock()
    return control


def test_setup_login_step_up_logout(ac: AccessControl) -> None:
    assert not ac.passphrase.is_set()
    with pytest.raises(NotSetUp):
        ac.login("u1", "One", "anything-at-all")
    with pytest.raises(ValueError):
        ac.setup("u1", "One", "short")
    ac.setup("u1", "One", "correct horse battery")
    with pytest.raises(AuthError):
        ac.setup("u1", "One", "correct horse battery")
    s = ac.login("u1", "One", "correct horse battery")
    assert ac.resolve(s.token, "u1") is s
    assert ac.resolve(s.token, "u2") is None
    assert not s.can_write(ac.clock())
    ac.step_up(s, "correct horse battery")
    assert s.can_write(ac.clock())
    ac.logout(s)
    assert ac.resolve(s.token, "u1") is None
    events = [
        json.loads(line)["event"] for line in (ac.data_dir / "audit.jsonl").read_text().splitlines()
    ]
    assert events == [
        "login_failed",
        "setup",
        "login",
        "session_user_mismatch",
        "step_up",
        "logout",
    ]


def test_session_expiry_and_idle(ac: AccessControl) -> None:
    ac.setup("u1", "One", "correct horse battery")
    s = ac.login("u1", "One", "correct horse battery")
    clock = ac.clock
    assert isinstance(clock, Clock)
    clock.now += security.SESSION_TTL - 1
    assert ac.resolve(s.token, "u1") is s
    assert ac.idle_seconds() == 0
    clock.now += security.SESSION_TTL + 1
    assert ac.resolve(s.token, "u1") is None
    assert ac.idle_seconds() == float("inf")


def test_lockout_after_failures(ac: AccessControl) -> None:
    ac.setup("u1", "One", "correct horse battery")
    for _ in range(security.LOCKOUT_FAILURES - 1):
        with pytest.raises(BadPassphrase):
            ac.login("u1", "One", "wrong wrong wrong")
    with pytest.raises(LockedOut):
        ac.login("u1", "One", "wrong wrong wrong")
    with pytest.raises(LockedOut):
        ac.login("u1", "One", "correct horse battery")
    clock = ac.clock
    assert isinstance(clock, Clock)
    clock.now += security.LOCKOUT_SECONDS + 1
    assert ac.login("u1", "One", "correct horse battery").user_id == "u1"


def test_rotate_requires_current(ac: AccessControl) -> None:
    ac.setup("u1", "One", "correct horse battery")
    s = ac.login("u1", "One", "correct horse battery")
    with pytest.raises(BadPassphrase):
        ac.rotate(s, "not the current one", "another good passphrase")
    ac.rotate(s, "correct horse battery", "another good passphrase")
    assert ac.passphrase.check("another good passphrase")


def test_audit_chain_detects_tampering(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl")
    log.record("a", "u", "U")
    log.record("b", "u", "U", frame="83 00 00 01")
    log.record("c", "u", "U")
    assert log.verify() == (True, 3)
    lines = (tmp_path / "audit.jsonl").read_text().splitlines()
    tampered = json.loads(lines[1])
    tampered["details"]["frame"] = "85 00 00 01"
    lines[1] = json.dumps(tampered, sort_keys=True)
    (tmp_path / "audit.jsonl").write_text("\n".join(lines) + "\n")
    assert AuditLog(tmp_path / "audit.jsonl").verify() == (False, 2)
    # A fresh instance continues the chain from the last line on disk.
    again = AuditLog(tmp_path / "audit.jsonl")
    again.record("d", "u", "U")
    assert again.verify() == (False, 2)

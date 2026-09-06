"""App-mode access control: passphrase, sessions, lockout, and the audit chain.

Everything here enforces a boundary described in docs/app.md. The passphrase
hash lives in a file under the data directory with restrictive permissions;
the audit log is an append-only JSON lines file where each line commits to
the previous one, so an edit anywhere breaks the chain from that point on.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1
SESSION_TTL = 15 * 60
STEP_UP_TTL = 15 * 60
LOCKOUT_FAILURES = 5
LOCKOUT_SECONDS = 15 * 60
FAILURE_DELAY = 1.0


class AuthError(Exception):
    pass


class NotSetUp(AuthError):
    pass


class LockedOut(AuthError):
    pass


class BadPassphrase(AuthError):
    pass


def _hash(passphrase: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        passphrase.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32
    )


class PassphraseStore:
    """The one app passphrase, as a salted scrypt hash on disk."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def is_set(self) -> bool:
        return self.path.is_file()

    def set(self, passphrase: str) -> None:
        if len(passphrase) < 12:
            raise ValueError("passphrase must be at least 12 characters")
        salt = secrets.token_bytes(16)
        doc = {"salt": salt.hex(), "hash": _hash(passphrase, salt).hex(), "n": SCRYPT_N}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc), encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)

    def check(self, passphrase: str) -> bool:
        if not self.is_set():
            raise NotSetUp("no passphrase has been set")
        doc = json.loads(self.path.read_text(encoding="utf-8"))
        expected = bytes.fromhex(doc["hash"])
        return hmac.compare_digest(_hash(passphrase, bytes.fromhex(doc["salt"])), expected)


@dataclass
class Session:
    token: str
    user_id: str
    user_name: str
    created: float
    last_seen: float
    write_until: float = 0.0

    def alive(self, now: float) -> bool:
        return now - self.last_seen < SESSION_TTL

    def can_write(self, now: float) -> bool:
        return self.write_until > now


@dataclass
class Lockout:
    failures: int = 0
    until: float = 0.0

    def check(self, now: float) -> None:
        if self.until > now:
            raise LockedOut(f"locked out for {int(self.until - now)} more seconds")

    def failed(self, now: float) -> bool:
        """Record a failure; return True when this one triggers the lockout."""
        self.failures += 1
        if self.failures >= LOCKOUT_FAILURES:
            self.failures = 0
            self.until = now + LOCKOUT_SECONDS
            return True
        return False

    def succeeded(self) -> None:
        self.failures = 0


class AuditLog:
    """Append-only JSON lines with a hash chain."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._last_hash = self._tail_hash()

    def _tail_hash(self) -> str:
        if not self.path.is_file():
            return ""
        last = ""
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    last = line
        if not last:
            return ""
        return str(json.loads(last).get("hash", ""))

    @staticmethod
    def _digest(content: dict[str, Any], previous: str) -> str:
        payload = json.dumps(content, sort_keys=True, separators=(",", ":")) + previous
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def record(self, event: str, user_id: str, user_name: str, **details: Any) -> dict[str, Any]:
        content = {
            "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": event,
            "user_id": user_id,
            "user_name": user_name,
            "details": details,
            "previous": self._last_hash,
        }
        entry = {**content, "hash": self._digest(content, self._last_hash)}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")
        self._last_hash = str(entry["hash"])
        return entry

    def verify(self) -> tuple[bool, int]:
        """Walk the chain; return (intact, number of the first bad line or the count)."""
        if not self.path.is_file():
            return True, 0
        previous = ""
        n = 0
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                n += 1
                entry = json.loads(line)
                stored = entry.pop("hash", "")
                if entry.get("previous") != previous or self._digest(entry, previous) != stored:
                    return False, n
                previous = stored
        return True, n


@dataclass
class AccessControl:
    """The state one running service keeps: passphrase, sessions, lockout, audit."""

    data_dir: Path
    allowed_users: frozenset[str]
    passphrase: PassphraseStore = field(init=False)
    audit: AuditLog = field(init=False)
    sessions: dict[str, Session] = field(default_factory=dict)
    lockout: Lockout = field(default_factory=Lockout)
    clock: Any = time.time

    def __post_init__(self) -> None:
        self.passphrase = PassphraseStore(self.data_dir / "passphrase.json")
        self.audit = AuditLog(self.data_dir / "audit.jsonl")

    def user_allowed(self, user_id: str) -> bool:
        return bool(user_id) and user_id in self.allowed_users

    def setup(self, user_id: str, user_name: str, passphrase: str) -> None:
        if self.passphrase.is_set():
            raise AuthError("a passphrase is already set; rotate it instead")
        self.passphrase.set(passphrase)
        self.audit.record("setup", user_id, user_name)

    def rotate(self, session: Session, current: str, new: str) -> None:
        self._check(session.user_id, session.user_name, current, "rotate")
        self.passphrase.set(new)
        self.audit.record("rotate", session.user_id, session.user_name)

    def _check(self, user_id: str, user_name: str, passphrase: str, purpose: str) -> None:
        now = self.clock()
        self.lockout.check(now)
        try:
            ok = self.passphrase.check(passphrase)
        except NotSetUp:
            self.audit.record("login_failed", user_id, user_name, reason="not set up")
            raise
        if ok:
            self.lockout.succeeded()
            return
        time.sleep(FAILURE_DELAY)
        locked = self.lockout.failed(now)
        self.audit.record("login_failed", user_id, user_name, purpose=purpose)
        if locked:
            self.audit.record("lockout", user_id, user_name, seconds=LOCKOUT_SECONDS)
            raise LockedOut("too many failures; locked out")
        raise BadPassphrase("wrong passphrase")

    def login(self, user_id: str, user_name: str, passphrase: str) -> Session:
        self._check(user_id, user_name, passphrase, "login")
        now = self.clock()
        session = Session(secrets.token_urlsafe(32), user_id, user_name, now, now)
        self.sessions[session.token] = session
        self.audit.record("login", user_id, user_name)
        return session

    def resolve(self, token: str | None, user_id: str) -> Session | None:
        """Return the live session for this token if it belongs to this user."""
        if not token:
            return None
        session = self.sessions.get(token)
        now = self.clock()
        if session is None or not session.alive(now):
            self.sessions.pop(token, None)
            return None
        if session.user_id != user_id:
            self.audit.record("session_user_mismatch", user_id, "", session_user=session.user_id)
            return None
        session.last_seen = now
        return session

    def step_up(self, session: Session, passphrase: str) -> None:
        self._check(session.user_id, session.user_name, passphrase, "step_up")
        session.write_until = self.clock() + STEP_UP_TTL
        self.audit.record("step_up", session.user_id, session.user_name)

    def logout(self, session: Session) -> None:
        self.sessions.pop(session.token, None)
        self.audit.record("logout", session.user_id, session.user_name)

    def idle_seconds(self) -> float:
        now = self.clock()
        live = [s.last_seen for s in self.sessions.values() if s.alive(now)]
        return now - max(live) if live else float("inf")

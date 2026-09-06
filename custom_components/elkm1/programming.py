"""Tracking of remote programming sessions: who programmed the panel, and when.

The panel reports only that a remote programming (RP) session is open or
closed; it cannot say who opened it, because the Elk Programmer app and
ElkRP look identical to it. Attribution therefore comes from a claim: the
app calls `elkm1.programming_session_start` before it logs in and
`elkm1.programming_session_end` when it is done. This module keeps the
current claim and a short history in storage shared by every entry, matches
the panel's own RP status against the claim, fires the programming events,
and raises a Repair issue when the two disagree. See docs/design.md,
"Programming session tracking".
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store

from .const import (
    DOMAIN,
    EVENT_ELKM1_PROGRAMMING_ENDED,
    EVENT_ELKM1_PROGRAMMING_STARTED,
)

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = f"{DOMAIN}.programming"
STORAGE_VERSION = 1
HISTORY_LIMIT = 20
SOURCE_UNATTRIBUTED = "unattributed"
ISSUE_UNATTRIBUTED = "programming_unattributed"
ISSUE_CLAIM_UNMATCHED = "programming_claim_unmatched"
CLAIM_UNMATCHED_AFTER_SECONDS = 300


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class Claim:
    """An announced session: the app said it is about to program the panel."""

    source: str
    user: str
    purpose: str
    claimed_at: str
    rp_seen: bool = False


@dataclass(slots=True)
class SessionRecord:
    """One finished or running session as the history keeps it."""

    source: str
    user: str
    purpose: str
    started: str
    ended: str | None
    attributed: bool
    rp_seen: bool


@dataclass(slots=True)
class ProgrammingState:
    claim: Claim | None = None
    unattributed_started: str | None = None
    rp_connected: bool = False
    history: list[SessionRecord] = field(default_factory=list)
    session_count: int = 0

    @property
    def last_started(self) -> str | None:
        return self.history[-1].started if self.history else None

    @property
    def last_ended(self) -> str | None:
        return self.history[-1].ended if self.history else None

    @property
    def source(self) -> str | None:
        if self.claim is not None:
            return self.claim.source
        if self.unattributed_started is not None:
            return SOURCE_UNATTRIBUTED
        return self.history[-1].source if self.history else None


class ProgrammingTracker:
    """Domain-wide state for programming sessions, persisted across restarts."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.state = ProgrammingState()
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._listeners: set[Callable[[], None]] = set()
        self._loaded = False

    async def async_load(self) -> None:
        if self._loaded:
            return
        data = await self._store.async_load()
        if data:
            claim = data.get("claim")
            self.state.claim = Claim(**claim) if claim else None
            self.state.history = [SessionRecord(**r) for r in data.get("history", [])]
            self.state.session_count = int(data.get("session_count", 0))
        self._loaded = True

    def _data(self) -> dict[str, Any]:
        return {
            "claim": asdict(self.state.claim) if self.state.claim else None,
            "history": [asdict(r) for r in self.state.history],
            "session_count": self.state.session_count,
        }

    def _save(self) -> None:
        """Deferred write, for the panel-driven path that runs in a sync callback."""
        self._store.async_delay_save(self._data, 1)

    async def _async_save(self) -> None:
        """Immediate write: a claim must survive a crash between start and end."""
        await self._store.async_save(self._data())

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)

    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    def _append(self, record: SessionRecord) -> None:
        self.state.history.append(record)
        del self.state.history[:-HISTORY_LIMIT]
        self.state.session_count += 1

    async def async_claim(self, source: str, user: str, purpose: str) -> None:
        """Record that `source` is about to open a programming session."""
        await self.async_load()
        if self.state.claim is not None:
            _LOGGER.warning(
                "programming session claimed by %s while %s still holds a claim; replacing it",
                source,
                self.state.claim.source,
            )
            self._close_claim(ended=_now())
        self.state.claim = Claim(source, user, purpose, _now(), rp_seen=self.state.rp_connected)
        if self.state.unattributed_started is not None:
            # The panel already reported a session no one had claimed; this claim owns it.
            self.state.unattributed_started = None
            self._delete_issue(ISSUE_UNATTRIBUTED)
        self.hass.bus.async_fire(
            EVENT_ELKM1_PROGRAMMING_STARTED,
            {
                "source": source,
                "user": user,
                "purpose": purpose,
                "attributed": True,
                "rp_seen": self.state.claim.rp_seen,
            },
        )
        await self._async_save()
        self._notify()

    async def async_end(self, source: str, user: str) -> None:
        """Record that `source` closed its session."""
        await self.async_load()
        claim = self.state.claim
        if claim is None:
            _LOGGER.warning("programming session end from %s with no claim open", source)
            return
        if claim.source != source:
            _LOGGER.warning(
                "programming session end from %s but the claim belongs to %s", source, claim.source
            )
        self._close_claim(ended=_now(), user=user or claim.user)
        self._delete_issue(ISSUE_CLAIM_UNMATCHED)
        await self._async_save()
        self._notify()

    def _close_claim(self, ended: str, user: str | None = None) -> None:
        claim = self.state.claim
        if claim is None:
            return
        record = SessionRecord(
            claim.source,
            user or claim.user,
            claim.purpose,
            claim.claimed_at,
            ended,
            True,
            claim.rp_seen,
        )
        self._append(record)
        self.state.claim = None
        self.hass.bus.async_fire(
            EVENT_ELKM1_PROGRAMMING_ENDED,
            {
                "source": record.source,
                "user": record.user,
                "purpose": record.purpose,
                "attributed": True,
                "rp_seen": record.rp_seen,
                "started": record.started,
                "ended": record.ended,
            },
        )

    @callback
    def async_rp_status(self, entry_id: str, connected: bool) -> None:
        """The panel's own RP status changed on a connected entry."""
        self.state.rp_connected = connected
        if connected:
            if self.state.claim is not None:
                self.state.claim.rp_seen = True
                self._delete_issue(ISSUE_CLAIM_UNMATCHED)
            elif self.state.unattributed_started is None:
                self.state.unattributed_started = _now()
                self.hass.bus.async_fire(
                    EVENT_ELKM1_PROGRAMMING_STARTED,
                    {
                        "source": SOURCE_UNATTRIBUTED,
                        "user": "",
                        "purpose": "",
                        "attributed": False,
                        "rp_seen": True,
                    },
                )
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    f"{ISSUE_UNATTRIBUTED}_{entry_id}",
                    is_fixable=False,
                    issue_domain=DOMAIN,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key=ISSUE_UNATTRIBUTED,
                    translation_placeholders={"started": self.state.unattributed_started},
                )
        elif self.state.unattributed_started is not None:
            record = SessionRecord(
                SOURCE_UNATTRIBUTED, "", "", self.state.unattributed_started, _now(), False, True
            )
            self.state.unattributed_started = None
            self._append(record)
            self.hass.bus.async_fire(
                EVENT_ELKM1_PROGRAMMING_ENDED,
                {
                    "source": record.source,
                    "user": "",
                    "purpose": "",
                    "attributed": False,
                    "rp_seen": True,
                    "started": record.started,
                    "ended": record.ended,
                },
            )
        self._save()
        self._notify()

    @callback
    def async_check_claim(self, entry_id: str) -> None:
        """Raise a Repair issue when a claim has waited too long for the panel's RP status.

        Called from a connected entry's periodic refresh, so it never fires
        while the entry is disabled for a serial session, which is the
        expected state on serial and not a fault.
        """
        claim = self.state.claim
        if claim is None or claim.rp_seen:
            return
        age = datetime.now(UTC) - datetime.fromisoformat(claim.claimed_at)
        if age.total_seconds() < CLAIM_UNMATCHED_AFTER_SECONDS:
            return
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            f"{ISSUE_CLAIM_UNMATCHED}_{entry_id}",
            is_fixable=False,
            issue_domain=DOMAIN,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_CLAIM_UNMATCHED,
            translation_placeholders={"source": claim.source, "claimed_at": claim.claimed_at},
        )

    def _delete_issue(self, prefix: str) -> None:
        registry = ir.async_get(self.hass)
        for issue in list(registry.issues.values()):
            if issue.domain == DOMAIN and issue.issue_id.startswith(prefix):
                ir.async_delete_issue(self.hass, DOMAIN, issue.issue_id)

    def diagnostics(self) -> dict[str, Any]:
        return {
            "claim": asdict(self.state.claim) if self.state.claim else None,
            "rp_connected": self.state.rp_connected,
            "unattributed_started": self.state.unattributed_started,
            "session_count": self.state.session_count,
            "history": [asdict(r) for r in self.state.history],
        }


@callback
def async_get_tracker(hass: HomeAssistant) -> ProgrammingTracker:
    """The one tracker per Home Assistant instance."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    tracker = domain_data.get("programming")
    if tracker is None:
        tracker = ProgrammingTracker(hass)
        domain_data["programming"] = tracker
    return tracker  # type: ignore[no-any-return]

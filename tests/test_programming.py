"""Programming session tracking: claims, the panel's RP status, events, Repairs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.elkm1.const import (
    CONF_CONNECTION_TYPE,
    CONF_PIN,
    CONF_SERIAL_PORT,
    CONNECTION_SERIAL,
    DOMAIN,
    EVENT_ELKM1_PROGRAMMING_ENDED,
    EVENT_ELKM1_PROGRAMMING_STARTED,
)
from custom_components.elkm1.coordinator import ElkDataUpdateCoordinator
from custom_components.elkm1.helpers.elk.const import ElkRPStatus
from custom_components.elkm1.programming import (
    CLAIM_UNMATCHED_AFTER_SECONDS,
    ISSUE_CLAIM_UNMATCHED,
    ISSUE_UNATTRIBUTED,
    SOURCE_UNATTRIBUTED,
    ProgrammingTracker,
    async_get_tracker,
)


def _issues(hass) -> list[str]:
    return sorted(i.issue_id for i in ir.async_get(hass).issues.values() if i.domain == DOMAIN)


async def test_claimed_session_is_attributed_and_persisted(hass):
    started = async_capture_events(hass, EVENT_ELKM1_PROGRAMMING_STARTED)
    ended = async_capture_events(hass, EVENT_ELKM1_PROGRAMMING_ENDED)
    tracker = async_get_tracker(hass)
    assert async_get_tracker(hass) is tracker

    await tracker.async_claim("elk_programmer", "user-1", "receive")
    assert tracker.state.claim is not None and tracker.state.source == "elk_programmer"
    assert started[-1].data == {
        "source": "elk_programmer",
        "user": "user-1",
        "purpose": "receive",
        "attributed": True,
        "rp_seen": False,
    }

    tracker.async_rp_status("entry", True)
    assert tracker.state.claim.rp_seen is True
    assert _issues(hass) == []
    tracker.async_rp_status("entry", False)
    await tracker.async_end("elk_programmer", "user-1")
    assert tracker.state.claim is None
    assert tracker.state.session_count == 1
    assert tracker.state.history[-1].attributed is True
    assert ended[-1].data["source"] == "elk_programmer" and ended[-1].data["attributed"] is True

    # A fresh tracker reloads the history from storage.
    await hass.async_block_till_done()
    fresh = ProgrammingTracker(hass)
    await fresh.async_load()
    assert fresh.state.session_count == 1
    assert fresh.state.history[-1].source == "elk_programmer"


async def test_unclaimed_session_is_unattributed_with_a_repair(hass):
    started = async_capture_events(hass, EVENT_ELKM1_PROGRAMMING_STARTED)
    ended = async_capture_events(hass, EVENT_ELKM1_PROGRAMMING_ENDED)
    tracker = async_get_tracker(hass)
    tracker.async_rp_status("entry", True)
    assert started[-1].data["source"] == SOURCE_UNATTRIBUTED
    assert started[-1].data["attributed"] is False
    assert _issues(hass) == [f"{ISSUE_UNATTRIBUTED}_entry"]
    tracker.async_rp_status("entry", False)
    assert ended[-1].data["attributed"] is False
    assert tracker.state.history[-1].source == SOURCE_UNATTRIBUTED
    # The issue stays for the user to review; a later, unrelated claim does not clear it.
    await tracker.async_claim("elk_programmer", "user-1", "send")
    assert _issues(hass) == [f"{ISSUE_UNATTRIBUTED}_entry"]


async def test_late_claim_adopts_a_running_unattributed_session(hass):
    tracker = async_get_tracker(hass)
    tracker.async_rp_status("entry", True)
    assert _issues(hass) == [f"{ISSUE_UNATTRIBUTED}_entry"]
    await tracker.async_claim("elk_programmer", "user-1", "receive")
    assert tracker.state.unattributed_started is None
    assert tracker.state.claim is not None and tracker.state.claim.rp_seen is True
    assert _issues(hass) == []


async def test_stale_claim_raises_a_repair_until_the_session_ends(hass):
    tracker = async_get_tracker(hass)
    await tracker.async_claim("elk_programmer", "user-1", "receive")
    tracker.async_check_claim("entry")
    assert _issues(hass) == []
    old = datetime.now(UTC) - timedelta(seconds=CLAIM_UNMATCHED_AFTER_SECONDS + 1)
    tracker.state.claim.claimed_at = old.isoformat()
    tracker.async_check_claim("entry")
    assert _issues(hass) == [f"{ISSUE_CLAIM_UNMATCHED}_entry"]
    await tracker.async_end("elk_programmer", "user-1")
    assert _issues(hass) == []


async def test_end_without_claim_is_ignored(hass, caplog):
    tracker = async_get_tracker(hass)
    await tracker.async_end("elk_programmer", "user-1")
    assert tracker.state.session_count == 0
    assert "no claim open" in caplog.text


async def test_services_are_registered_and_reach_the_tracker(hass):
    from custom_components.elkm1.services import async_setup_services

    await async_setup_services(hass)
    assert hass.services.has_service(DOMAIN, "programming_session_start")
    assert hass.services.has_service(DOMAIN, "programming_session_end")
    await hass.services.async_call(
        DOMAIN,
        "programming_session_start",
        {"source": "elk_programmer", "user": "user-1", "purpose": "verify"},
        blocking=True,
    )
    assert async_get_tracker(hass).state.claim.purpose == "verify"
    await hass.services.async_call(
        DOMAIN, "programming_session_end", {"source": "elk_programmer"}, blocking=True
    )
    assert async_get_tracker(hass).state.claim is None


@pytest.mark.parametrize("_patch_login", [True], indirect=True)
async def test_coordinator_feeds_rp_and_ie_to_the_tracker(hass, _patch_login):
    coordinator = ElkDataUpdateCoordinator(
        hass,
        {CONF_CONNECTION_TYPE: CONNECTION_SERIAL, CONF_SERIAL_PORT: "COM3", CONF_PIN: "1234"},
    )
    coordinator.config_entry = SimpleNamespace(entry_id="entry")
    with patch.object(coordinator, "_build_normalized_data", return_value=coordinator.data):
        coordinator._handle_rp_status(ElkRPStatus.CONNECTED)
        tracker = async_get_tracker(hass)
        assert tracker.state.rp_connected is True
        assert _issues(hass) == [f"{ISSUE_UNATTRIBUTED}_entry"]
        coordinator._handle_installer_exit()
        assert tracker.state.rp_connected is False
        assert tracker.state.history[-1].source == SOURCE_UNATTRIBUTED


@pytest.fixture
def _patch_login(request):
    succeeded = request.param

    def fake_start(self) -> None:
        self.elk._notifier.notify("login", {"succeeded": succeeded})

    with patch(
        "custom_components.elkm1.coordinator.ElkConnectionManager.start",
        fake_start,
    ):
        yield

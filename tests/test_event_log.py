"""Unit tests for event_log.py's ELK_EVENT_DESCRIPTIONS table and
describe_elk_event(). Added 2026-09-05 alongside wiring the LD (system log)
event's numeric code to a human-readable description - see
docs/decisions.md.
"""

from __future__ import annotations

from custom_components.elkm1.event_log import ELK_EVENT_DESCRIPTIONS, describe_elk_event


def test_table_has_every_event_extracted_from_the_reference_database():
    assert len(ELK_EVENT_DESCRIPTIONS) == 1358


def test_describe_elk_event_known_codes():
    assert describe_elk_event(1000) == "no event"
    assert describe_elk_event(1001) == "fire alarm"
    assert describe_elk_event(4176) == "zone 176 state"
    assert describe_elk_event(7208) == "output 208 state"


def test_describe_elk_event_falls_back_for_an_unknown_code():
    assert describe_elk_event(999999) == "unknown event 999999"


def test_every_description_is_a_non_empty_lowercase_string():
    for code, description in ELK_EVENT_DESCRIPTIONS.items():
        assert isinstance(code, int)
        assert description
        assert description == description.lower()

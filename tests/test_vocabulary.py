"""Unit tests for vocabulary.py's ELK_VOICE_VOCABULARY table and
translate_elk_voice(). Regression coverage for the 2026-09-05 fix (see
docs/decisions.md): the "say toggle" phrase IDs were wrong (positive
instead of negative, several missing entirely), found by comparing against
Elk's own WordLists reference table extracted from ElkRP.
"""

from __future__ import annotations

import pytest

from custom_components.elkm1.vocabulary import ELK_VOICE_VOCABULARY, translate_elk_voice


@pytest.mark.parametrize(
    ("word_id", "expected"),
    [
        (-512, "[say on/off]"),
        (-511, "[say off/on]"),
        (-510, "[say open/closed]"),
        (-509, "[say closed/open]"),
        (-508, "[say up/down]"),
        (-507, "[say down/up]"),
        (-506, "[say secure/not secure]"),
        (-505, "[say not secure/secure]"),
        (-504, "[say locked/unlocked]"),
        (-503, "[say unlocked/locked]"),
        (-5, "[say number]"),
        (-4, "[inverted condition]"),
        (-3, "[insert time]"),
        (-2, "[insert condition]"),
    ],
)
def test_negative_ids_are_the_say_toggle_and_template_tokens(word_id, expected):
    assert ELK_VOICE_VOCABULARY[word_id] == expected


def test_no_stale_positive_say_toggle_ids_remain():
    """The old (wrong) table used positive 495/496/505-512 for these
    phrases; they must not still be present with that meaning."""
    for stale_id in (495, 496, 505, 506, 507, 508, 509, 510, 511, 512):
        assert stale_id not in ELK_VOICE_VOCABULARY


def test_positive_custom_ids_are_distinct_from_negative_template_tokens():
    """IDs 2/3/4 and -2/-3/-4 are genuinely different, non-overlapping
    entries in the real table, not one ambiguous ID space."""
    assert ELK_VOICE_VOCABULARY[2] == "custom 2"
    assert ELK_VOICE_VOCABULARY[3] == "custom 3"
    assert ELK_VOICE_VOCABULARY[4] == "custom 4"
    assert ELK_VOICE_VOCABULARY[-2] == "[insert condition]"
    assert ELK_VOICE_VOCABULARY[-3] == "[insert time]"
    assert ELK_VOICE_VOCABULARY[-4] == "[inverted condition]"


def test_translate_elk_voice_handles_a_negative_id():
    assert translate_elk_voice([471, -507, 464]) == "zone [say down/up] window"


def test_translate_elk_voice_skips_blank_and_tone_ids():
    assert translate_elk_voice([0, 51, 52, 53, 471]) == "zone"


def test_translate_elk_voice_flags_an_unknown_id():
    assert translate_elk_voice([9999]) == "[Unknown ID: 9999]"


def test_translate_elk_voice_ignores_non_numeric_ids():
    assert translate_elk_voice(["not-a-number", 471]) == "zone"


def test_translate_elk_voice_returns_empty_string_for_no_ids():
    assert translate_elk_voice([]) == ""

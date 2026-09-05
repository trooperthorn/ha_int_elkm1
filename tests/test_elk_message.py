"""Unit tests for every encode/decode function in helpers/elk/message.py.

Closes the gap left by the 2026-09-05 elkm1-lib removal (see docs/decisions.md):
that port's own plan called for "new unit tests assert every encode/decode
function against the exact worked examples already extracted from the primary
spec PDF", which had not actually been written - only a handful of functions
were exercised indirectly through test_protocol.py/test_transport.py.

Test data sources, in order of preference:
1. Real hardware captures from this session's live-hardware pass against the
   COM3 panel (docs/live_qualification.md) - `vn`, `as`, `ss`, `kc`, `rr`,
   `st`, `ld`.
2. Literal worked examples from `ELK-M1_RS232_PROTOCOL.Ver+1.90.pdf` - the two
   `AS` examples (section 4.2), the three `IC` examples (section 4.16), and
   the `AM` no-reserved-field wire format (section 4.37).
3. Hand-derived synthetic frames built from this module's own documented
   field offsets, for functions with no captured or spec-literal example
   available. These are independent of `message.py`'s own encode/checksum
   logic (built with a separately-coded checksum formula, matching the
   `_wire()` helper already used in test_protocol.py/test_transport.py) but
   do rely on this file's author having read the field-offset arithmetic
   correctly - noted per-function where that matters.
"""

from __future__ import annotations

import datetime as dt
import os
import time

import pytest

from custom_components.elkm1.helpers.elk import message
from custom_components.elkm1.helpers.elk.const import (
    AlarmState,
    ArmedStatus,
    ArmLevel,
    ArmUpState,
    ChimeMode,
    ElkRPStatus,
    FunctionKeys,
    SettingFormat,
    ThermostatFan,
    ThermostatMode,
    ThermostatSetting,
    ZoneAlarmState,
    ZoneLogicalStatus,
    ZonePhysicalStatus,
    ZoneType,
)


def _wire(command: str, data: str = "") -> str:
    """Build a standard NNMSD...00CC frame with an independently-coded checksum."""
    body = f"{len(data) + 6:02X}{command}{data}00"
    check = (256 - sum(map(ord, body))) % 256
    return f"{body}{check:02X}"


def _wire_no_reserved(command: str, data: str) -> str:
    """Build a frame with no "00" reserved field (the `AM` broadcast's format
    per spec section 4.37 - `0CAMSSSSSSSSCC`, straight from data to checksum).
    """
    body = f"{len(data) + 4:02X}{command}{data}"
    check = (256 - sum(map(ord, body))) % 256
    return f"{body}{check:02X}"


# --------------------------------------------------------------------------
# Checksum and framing invariants
# --------------------------------------------------------------------------


def test_checksum_matches_independent_twos_complement_formula():
    body = "06vn00"
    assert message.checksum(body) == f"{(256 - sum(map(ord, body))) % 256:02X}"


def test_decode_returns_unknown_for_an_unrecognized_command():
    """`data` is `msg[4:-2]`, which includes the trailing "00" reserved bytes
    the standard wire format appends - not just the caller-supplied payload.
    """
    frame = _wire("ZZ", "hello")
    assert message.decode(frame) == ("unknown", {"msg_code": "ZZ", "data": "hello00"})


def test_decode_wraps_a_decoder_exception_as_value_error():
    """A non-hex version field passes length/checksum but fails inside
    `vn_decode`'s own `int(..., 16)` parsing - `decode()` must wrap that as a
    plain `ValueError`, not let the original one propagate."""
    frame = _wire("VN", "XX0003080000")
    with pytest.raises(ValueError, match="Cannot decode message"):
        message.decode(frame)


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("", None),
        ("Username: ", None),
        ("Password: ", None),
        ("Login successful", ("login", {"succeeded": True})),
        ("Username/Password not found", ("login", {"succeeded": False})),
        ("Disabled", ("login", {"succeeded": False})),
    ],
)
def test_decode_handles_the_non_framed_login_handshake_lines(line, expected):
    assert message.decode(line) == expected


def test_decode_raises_for_garbage_that_is_neither_a_valid_frame_nor_a_login_line():
    with pytest.raises(ValueError, match="Message invalid"):
        message.decode("not a real frame")


def test_pc_all_decode_rejects_a_house_letter_outside_a_through_p():
    """`_pc_all_decode` returns None for an out-of-range house letter before
    even trying to parse the aggregate code, falling through to the regular
    per-device `pc_decode` - which then itself rejects "Q00" as an invalid
    housecode (Q is outside A-P), so the overall decode still raises.
    """
    frame = _wire("PC", "Q0002")
    with pytest.raises(ValueError, match="Cannot decode message"):
        message.decode(frame)


def test_pc_all_decode_returns_none_for_a_non_numeric_aggregate_code():
    """A non-numeric aggregate-code field makes `_pc_all_decode` return None
    (exercising its own except-ValueError branch), falling through to the
    regular per-device `pc_decode` - which then itself rejects unit "00" as
    an invalid housecode (out of the 1-16 range), so the overall decode
    still raises for an unrelated reason.
    """
    frame = _wire("PC", "A00XX")
    with pytest.raises(ValueError, match="Cannot decode message"):
        message.decode(frame)


def test_st_decode_group_1_offsets_by_40():
    frame = _wire("ST", "101" + "072")
    assert message.decode(frame) == ("ST", {"group": 1, "device": 0, "temperature": 32})


ALL_ENCODERS = [
    ("al", lambda: message.al_encode(ArmLevel.ARMED_AWAY, 0, 1234)),
    ("as", message.as_encode),
    ("az", message.az_encode),
    ("cf", lambda: message.cf_encode(5)),
    ("ct", lambda: message.ct_encode(5)),
    ("cn", lambda: message.cn_encode(5, 30)),
    ("cs", message.cs_encode),
    ("cp", message.cp_encode),
    ("cr", lambda: message.cr_encode(3)),
    ("cw_number", lambda: message.cw_encode(3, 500, SettingFormat.NUMBER)),
    ("cw_time", lambda: message.cw_encode(0, (12, 30), SettingFormat.TIME_OF_DAY)),
    ("cv", lambda: message.cv_encode(3)),
    ("cx", lambda: message.cx_encode(3, 100)),
    ("dm", lambda: message.dm_encode(0, 1, True, 30, "Hi", "There")),
    ("ka", message.ka_encode),
    ("kc", lambda: message.kc_encode(0)),
    ("kf", lambda: message.kf_encode(0, FunctionKeys.STAR)),
    ("ld", lambda: message.ld_encode(1)),
    ("lw", message.lw_encode),
    ("pc", lambda: message.pc_encode(0, 2, 0, 30)),
    ("pf", lambda: message.pf_encode(0)),
    ("pn", lambda: message.pn_encode(0)),
    ("ps", lambda: message.ps_encode(0)),
    ("pt", lambda: message.pt_encode(0)),
    ("sd", lambda: message.sd_encode(0, 0)),
    ("sp", lambda: message.sp_encode(5)),
    ("ss", message.ss_encode),
    ("sw", lambda: message.sw_encode(5)),
    ("rr", message.rr_encode),
    ("rw", lambda: message.rw_encode(dt.datetime(2026, 1, 5, 10, 30, 45))),
    ("st", lambda: message.st_encode(0, 0)),
    ("tn", lambda: message.tn_encode(0)),
    ("tr", lambda: message.tr_encode(0)),
    ("ts", lambda: message.ts_encode(0, 70, ThermostatSetting.HEAT_SETPOINT)),
    ("ua", lambda: message.ua_encode(1234)),
    ("vn", message.vn_encode),
    ("zb_normal", lambda: message.zb_encode(0, 0, 1234)),
    ("zb_clear_all", lambda: message.zb_encode(-1, 0, 1234)),
    ("zb_bypass_all", lambda: message.zb_encode(300, 0, 1234)),
    ("zd", message.zd_encode),
    ("zp", message.zp_encode),
    ("zs", message.zs_encode),
    ("zt", lambda: message.zt_encode(0)),
    ("zv", lambda: message.zv_encode(0)),
]


@pytest.mark.parametrize(("name", "build"), ALL_ENCODERS, ids=[n for n, _ in ALL_ENCODERS])
def test_every_encoder_produces_a_self_consistent_checksum_valid_frame(name, build):
    """Every encoder's own length field and checksum must validate - a cheap,
    blanket structural check across all 33 encoders, independent of the
    per-function literal-string tests below.
    """
    encoded = build()
    valid, error = message._is_valid_length_and_checksum(encoded.message)
    assert valid, f"{name}: {error}"


# --------------------------------------------------------------------------
# Per-function encode tests: exact literal expected wire string
# --------------------------------------------------------------------------


def test_al_encode_arm_away():
    encoded = message.al_encode(ArmLevel.ARMED_AWAY, 0, 1234)
    assert encoded.message == _wire("a1", "1001234")
    assert encoded.response_command == "AS"


def test_as_encode():
    encoded = message.as_encode()
    assert encoded.message == _wire("as")
    assert encoded.response_command == "AS"


def test_az_encode():
    encoded = message.az_encode()
    assert encoded.message == _wire("az")
    assert encoded.response_command == "AZ"


def test_cf_encode_turns_off_one_based_output():
    encoded = message.cf_encode(5)
    assert encoded.message == _wire("cf", "006")
    assert encoded.response_command is None


def test_ct_encode_toggles_one_based_output():
    encoded = message.ct_encode(5)
    assert encoded.message == _wire("ct", "006")
    assert encoded.response_command is None


def test_cn_encode_turn_on_with_timed_seconds():
    encoded = message.cn_encode(5, 30)
    assert encoded.message == _wire("cn", "00600030")
    assert encoded.response_command is None


def test_cs_encode():
    encoded = message.cs_encode()
    assert encoded.message == _wire("cs")
    assert encoded.response_command == "CS"


def test_cp_encode_requests_all_custom_values():
    encoded = message.cp_encode()
    assert encoded.message == _wire("cp")
    assert encoded.response_command == "CR"


def test_cr_encode_requests_one_custom_value():
    encoded = message.cr_encode(3)
    assert encoded.message == _wire("cr", "04")
    assert encoded.response_command == "CR"


def test_cw_encode_number_format():
    encoded = message.cw_encode(3, 500, SettingFormat.NUMBER)
    assert encoded.message == _wire("cw", "0400500")
    assert encoded.response_command == "CR"


def test_cw_encode_time_of_day_format_packs_hour_and_minute():
    encoded = message.cw_encode(0, (12, 30), SettingFormat.TIME_OF_DAY)
    assert encoded.message == _wire("cw", f"01{12 * 256 + 30:05}")
    assert encoded.response_command == "CR"


def test_cv_encode():
    encoded = message.cv_encode(3)
    assert encoded.message == _wire("cv", "04")
    assert encoded.response_command == "CV"


def test_cx_encode_writes_counter_value():
    encoded = message.cx_encode(3, 100)
    assert encoded.message == _wire("cx", "0400100")
    assert encoded.response_command == "CV"


def test_dm_encode_pads_lines_to_16_chars_with_caret_fill():
    encoded = message.dm_encode(0, 1, True, 30, "Hi", "There")
    line1 = f"{'Hi':^<16.16}"
    line2 = f"{'There':^<16.16}"
    assert encoded.message == _wire("dm", f"11100030{line1}{line2}")
    assert encoded.response_command is None


def test_ka_encode():
    encoded = message.ka_encode()
    assert encoded.message == _wire("ka")
    assert encoded.response_command == "KA"


def test_kc_encode_requests_one_based_keypad_status():
    """No encoder existed for this in elkm1-lib 2.2.15 (see docs/decisions.md);
    also confirmed against real hardware in this session's live pass.
    """
    encoded = message.kc_encode(0)
    assert encoded.message == _wire("kc", "01")
    assert encoded.response_command == "KC"


def test_kf_encode_simulates_a_function_key_press():
    encoded = message.kf_encode(0, FunctionKeys.STAR)
    assert encoded.message == _wire("kf", "01*")
    assert encoded.response_command == "KF"


def test_kf_encode_defaults_to_force_sync():
    encoded = message.kf_encode(0)
    assert encoded.message == _wire("kf", "010")


def test_ld_encode_requests_indexed_log_entry():
    """No encoder existed for this in elkm1-lib 2.2.15 (see docs/decisions.md);
    also confirmed against real hardware in this session's live pass.
    """
    encoded = message.ld_encode(1)
    assert encoded.message == _wire("ld", "001")
    assert encoded.response_command == "LD"


def test_lw_encode():
    encoded = message.lw_encode()
    assert encoded.message == _wire("lw")
    assert encoded.response_command == "LW"


def test_pc_encode_builds_housecode_and_control_fields():
    encoded = message.pc_encode(0, 2, 0, 30)
    assert encoded.message == _wire("pc", "A0102000030")
    assert encoded.response_command is None


def test_pf_encode_turns_off_by_housecode():
    encoded = message.pf_encode(0)
    assert encoded.message == _wire("pf", "A01")


def test_pn_encode_turns_on_by_housecode():
    encoded = message.pn_encode(0)
    assert encoded.message == _wire("pn", "A01")


def test_ps_encode_requests_a_lighting_bank():
    encoded = message.ps_encode(0)
    assert encoded.message == _wire("ps", "0")
    assert encoded.response_command == "PS"


def test_pt_encode_toggles_by_housecode():
    encoded = message.pt_encode(0)
    assert encoded.message == _wire("pt", "A01")


def test_sd_encode_requests_a_text_description():
    encoded = message.sd_encode(0, 0)
    assert encoded.message == _wire("sd", "00001")
    assert encoded.response_command == "SD"


def test_sp_encode_speaks_a_phrase():
    encoded = message.sp_encode(5)
    assert encoded.message == _wire("sp", "005")
    assert encoded.response_command is None


def test_ss_encode():
    encoded = message.ss_encode()
    assert encoded.message == _wire("ss")
    assert encoded.response_command == "SS"


def test_sw_encode_speaks_a_word():
    encoded = message.sw_encode(5)
    assert encoded.message == _wire("sw", "005")
    assert encoded.response_command is None


def test_rr_encode_requests_the_rtc_directly():
    """No encoder existed for this in elkm1-lib 2.2.15 (see docs/decisions.md);
    also confirmed against real hardware in this session's live pass.
    """
    encoded = message.rr_encode()
    assert encoded.message == _wire("rr")
    assert encoded.response_command == "RR"


def test_rw_encode_declares_rr_as_its_reply():
    """Fixed relative to elkm1-lib 2.2.15, which declared no response_command
    for `rw` even though the protocol replies `RR` (see docs/decisions.md).
    """
    encoded = message.rw_encode(dt.datetime(2026, 1, 5, 10, 30, 45))
    weekday = (dt.datetime(2026, 1, 5).weekday() + 1) % 7 + 1
    expected_time_str = dt.datetime(2026, 1, 5, 10, 30, 45).strftime(
        "%S%M%H.%d%m%y"
    ).replace(".", str(weekday))
    assert encoded.message == _wire("rw", expected_time_str)
    assert encoded.response_command == "RR"


def test_st_encode_requests_temperature_for_one_probe():
    """No encoder existed for this in elkm1-lib 2.2.15 (see docs/decisions.md);
    also confirmed against real hardware in this session's live pass.
    """
    encoded = message.st_encode(0, 0)
    assert encoded.message == _wire("st", "001")
    assert encoded.response_command == "ST"


def test_tn_encode_activates_a_task():
    encoded = message.tn_encode(0)
    assert encoded.message == _wire("tn", "001")
    assert encoded.response_command is None


def test_tr_encode_declares_tr_as_its_own_reply():
    """Fixed relative to elkm1-lib 2.2.15, which declared no response_command
    for `tr` even though the protocol replies `TR` (see docs/decisions.md).
    """
    encoded = message.tr_encode(0)
    assert encoded.message == _wire("tr", "01")
    assert encoded.response_command == "TR"


def test_ts_encode_declares_tr_as_its_reply():
    """Fixed relative to elkm1-lib 2.2.15, which declared no response_command
    for `ts` even though the protocol replies `TR` (see docs/decisions.md).
    """
    encoded = message.ts_encode(0, 70, ThermostatSetting.HEAT_SETPOINT)
    assert encoded.message == _wire("ts", "01705")
    assert encoded.response_command == "TR"


def test_ua_encode_requests_valid_areas_for_a_user_code():
    encoded = message.ua_encode(1234)
    assert encoded.message == _wire("ua", "001234")
    assert encoded.response_command == "UA"


def test_vn_encode():
    encoded = message.vn_encode()
    assert encoded.message == _wire("vn")
    assert encoded.response_command == "VN"


@pytest.mark.parametrize(
    ("zone", "expected_zone_field"),
    [
        (0, "001"),  # normal 0-based zone, converted to 1-based
        (-1, "000"),  # clear-bypass-all
        (300, "999"),  # out of range clamps to bypass-all
    ],
)
def test_zb_encode_zone_field(zone, expected_zone_field):
    encoded = message.zb_encode(zone, 0, 1234)
    assert encoded.message == _wire("zb", f"{expected_zone_field}1001234")
    assert encoded.response_command == "ZB"


def test_zd_encode():
    encoded = message.zd_encode()
    assert encoded.message == _wire("zd")
    assert encoded.response_command == "ZD"


def test_zp_encode():
    encoded = message.zp_encode()
    assert encoded.message == _wire("zp")
    assert encoded.response_command == "ZP"


def test_zs_encode():
    encoded = message.zs_encode()
    assert encoded.message == _wire("zs")
    assert encoded.response_command == "ZS"


def test_zt_encode_triggers_a_zone():
    encoded = message.zt_encode(0)
    assert encoded.message == _wire("zt", "001")
    assert encoded.response_command is None


def test_zv_encode_requests_zone_voltage():
    encoded = message.zv_encode(0)
    assert encoded.message == _wire("zv", "001")
    assert encoded.response_command == "ZV"


# --------------------------------------------------------------------------
# Decode: real hardware captures (this session's live pass against COM3,
# see docs/live_qualification.md's fifth follow-up entry)
# --------------------------------------------------------------------------


def test_vn_decode_real_panel_capture():
    frame = "36VN0503120000000000000000000000000000000000000000000088"
    assert message.decode(frame) == (
        "VN",
        {"elkm1_version": "5.3.18", "xep_version": "0.0.0"},
    )


def test_as_decode_real_panel_capture_all_disarmed():
    frame = "1EAS000000000111111100000000000F"
    command, payload = message.decode(frame)
    assert command == "AS"
    assert payload["armed_statuses"] == [ArmedStatus.DISARMED] * 8
    assert payload["arm_up_states"] == [ArmUpState.NOT_READY_TO_ARM] + [
        ArmUpState.READY_TO_ARM
    ] * 7
    assert payload["alarm_states"] == [AlarmState.NO_ALARM_ACTIVE] * 8
    assert payload["timer_seconds"] == 0


def test_ss_decode_real_panel_capture():
    frame = "28SS0000000001000000000000000000000000002F"
    assert message.decode(frame) == (
        "SS",
        {"system_trouble_status": "000000000100000000000000000000000000"},
    )


def test_kc_decode_real_panel_capture_forced_reply_has_key_zero():
    """A `kc` request's forced reply has `key` forced to 0 per the spec, but
    (contrary to `kc_detail_decode`'s own docstring, which describes this as
    a case that returns `None`) this real captured frame is long enough to
    carry the full v1.90 supplemental field set too - the "forced key" only
    forces that one field, it does not shorten the frame. Both decodes were
    captured from the same real reply in this session's live pass.
    """
    frame = "19KC01000000001000000000016"
    assert message.decode(frame) == ("KC", {"keypad": 0, "key": 0})
    assert message.kc_detail_decode(frame) == {
        "keypad": 0,
        "key": 0,
        "function_key_lights": (0, 0, 0, 0, 0, 0),
        "bypass_requires_code": True,
        "beep_chime_by_area": (0, 0, 0, 0, 0, 0, 0, 0),
    }


def test_rr_decode_real_panel_capture():
    frame = "16RR11120170509261000071"
    assert message.decode(frame) == ("RR", {"real_time_clock": "1112017050926100"})


def test_st_decode_real_panel_capture_no_probe_enrolled():
    frame = "0CST0010000065"
    assert message.decode(frame) == (
        "ST",
        {"group": 0, "device": 0, "temperature": -60},
    )


def test_ld_decode_real_panel_capture():
    """ld_decode() has no timezone field on the wire - it converts the
    panel's local wall-clock time to UTC using the host machine's own local
    timezone (the documented assumption for a locally-installed HA instance).
    This real hardware capture was taken at UTC-5 (fixed offset, no DST), so
    the test pins TZ to that offset rather than depending on whatever
    timezone happens to run the suite.
    """
    original_tz = os.environ.get("TZ")
    os.environ["TZ"] = "Etc/GMT+5"
    time.tzset()
    try:
        frame = "1CLD1159001100000905001726004C"
        assert message.decode(frame) == (
            "LD",
            {
                "area": 0,
                "log": {
                    "event": 1159,
                    "number": 1,
                    "index": 1,
                    "timestamp": "2026-09-05T05:00:00+00:00",
                },
            },
        )
    finally:
        if original_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original_tz
        time.tzset()


# --------------------------------------------------------------------------
# Decode: literal manufacturer worked examples
# (ELK-M1_RS232_PROTOCOL.Ver+1.90.pdf)
# --------------------------------------------------------------------------


def test_as_decode_spec_example_exit_timer_9_seconds():
    """Section 4.2: "1EAS1000000031111111000000000902 - Exit time set to 9 seconds."."""
    frame = "1EAS1000000031111111000000000902"
    command, payload = message.decode(frame)
    assert command == "AS"
    assert payload["armed_statuses"][0] == ArmedStatus.ARMED_AWAY
    assert payload["arm_up_states"][0] == ArmUpState.ARMED_AND_EXIT_TIMER_RUNNING
    assert payload["alarm_states"][0] == AlarmState.NO_ALARM_ACTIVE
    assert payload["timer_seconds"] == 9


def test_as_decode_spec_example_armed_away_full_fire_alarm():
    """Section 4.2: "1EAS100000004000000030000000000E - Area 1 is armed away,
    and the area is full fire alarm."."""
    frame = "1EAS100000004000000030000000000E"
    command, payload = message.decode(frame)
    assert command == "AS"
    assert payload["armed_statuses"][0] == ArmedStatus.ARMED_AWAY
    assert payload["arm_up_states"][0] == ArmUpState.FULLY_ARMED
    assert payload["alarm_states"][0] == AlarmState.FIRE_ALARM
    assert payload["timer_seconds"] == 0


def test_ic_decode_spec_example_1_invalid_keypad_code():
    """Section 4.16, Example 1: keypad-entered invalid code 3456 - only the
    low nibble of each of the 6 code bytes is a real digit, so the field
    decodes to "003456" (two zero-padding bytes ahead of the real 4 digits),
    not a stripped "3456". Checksum in the spec's own example is a literal
    "CC" placeholder, not a real value, so this calls `ic_decode` directly
    rather than routing through `decode()`'s checksum validation.
    """
    frame = "17IC0000030405060000100CC"
    assert message.ic_decode(frame) == {"code": "003456", "user": -1, "keypad": 0}


def test_ic_decode_spec_example_3_valid_code_hides_the_digits():
    """Section 4.16, Example 3: a valid code's digit field is all zeros by
    design ("This purposes hides all valid codes"), reporting only which
    stored user code number matched.
    """
    frame = "17IC000000000000003010078"
    assert message.ic_decode(frame) == {"code": "000000", "user": 2, "keypad": 0}


# --------------------------------------------------------------------------
# Decode: the `AM` broadcast's no-reserved-field wire format
# (ELK-M1_RS232_PROTOCOL.Ver+1.90.pdf section 4.37: `0CAMSSSSSSSSCC`, straight
# from the 8 area digits to the checksum, unlike every other message type)
# --------------------------------------------------------------------------


def test_am_decode_no_reserved_field_format():
    frame = _wire_no_reserved("AM", "10000001")
    assert message.decode(frame) == (
        "AM",
        {"alarm_memory": [True, False, False, False, False, False, False, True]},
    )


# --------------------------------------------------------------------------
# Decode: synthetic frames, hand-derived from this module's own documented
# field offsets (independent checksum via `_wire()`/`_wire_no_reserved()`)
# --------------------------------------------------------------------------


def test_az_decode_alarm_by_zone():
    data = "0" * 8 + "9" + "0" * 199
    frame = _wire("AZ", data)
    command, payload = message.decode(frame)
    assert command == "AZ"
    assert payload["alarm_status"][8] == ZoneAlarmState.BURGLAR_BOX_TAMPER
    assert payload["alarm_status"][0] == ZoneAlarmState.NO_ALARM
    assert len(payload["alarm_status"]) == 208


def test_cr_decode_single_custom_value():
    frame = _wire("CR", "03" + "001200")
    assert message.decode(frame) == (
        "CR",
        {"values": [{"index": 2, "value": 120, "value_format": SettingFormat.NUMBER}]},
    )


def test_cr_decode_time_of_day_format_unpacks_hour_and_minute():
    value = 12 * 256 + 30
    frame = _wire("CR", f"01{value:05}{SettingFormat.TIME_OF_DAY.value}")
    assert message.decode(frame) == (
        "CR",
        {"values": [{"index": 0, "value": (12, 30), "value_format": SettingFormat.TIME_OF_DAY}]},
    )


def test_cr_decode_all_custom_values():
    parts = ["00120" + "0"] + ["00000" + "0"] * 19
    frame = _wire("CR", "00" + "".join(parts))
    command, payload = message.decode(frame)
    assert command == "CR"
    assert len(payload["values"]) == 20
    assert payload["values"][0] == {
        "index": 0,
        "value": 120,
        "value_format": SettingFormat.NUMBER,
    }


def test_cc_decode_single_output_status_change():
    frame = _wire("CC", "0051")
    assert message.decode(frame) == ("CC", {"output": 4, "output_status": True})


def test_cs_decode_all_output_statuses():
    data = "1" + "0" * 207
    frame = _wire("CS", data)
    command, payload = message.decode(frame)
    assert command == "CS"
    assert payload["output_status"][0] is True
    assert payload["output_status"][1] is False
    assert len(payload["output_status"]) == 208


def test_cv_decode_counter_value():
    frame = _wire("CV", "03" + "00042")
    assert message.decode(frame) == ("CV", {"counter": 2, "value": 42})


def test_ee_decode_exit_timer():
    frame = _wire("EE", "100150001")
    assert message.decode(frame) == (
        "EE",
        {"area": 0, "is_exit": True, "timer1": 15, "timer2": 0, "armed_status": ArmedStatus.ARMED_AWAY},
    )


def test_ie_decode_has_no_payload_fields():
    frame = _wire("IE")
    assert message.decode(frame) == ("IE", {})


def test_ka_decode_keypad_area_assignments():
    data = "1" * 16
    frame = _wire("KA", data)
    command, payload = message.decode(frame)
    assert command == "KA"
    assert payload["keypad_areas"] == [0] * 16


def test_kf_decode_function_key_press_with_chime_modes():
    frame = _wire("KF", "011" + "01230123")
    command, payload = message.decode(frame)
    assert command == "KF"
    assert payload["keypad"] == 0
    assert payload["key"] == FunctionKeys.F1
    assert payload["chime_mode"] == [
        ChimeMode.OFF,
        ChimeMode.CHIME,
        ChimeMode.VOICE,
        ChimeMode.CHIMEANDVOICE,
    ] * 2


def test_lw_decode_keypad_and_zone_temperatures():
    data = "072" * 16 + "075" * 16
    frame = _wire("LW", data)
    command, payload = message.decode(frame)
    assert command == "LW"
    assert payload["keypad_temps"] == [32] * 16
    assert payload["zone_temps"] == [15] * 16


def test_pc_decode_single_device_change():
    frame = _wire("PC", "A0255")
    command, payload = message.decode(frame)
    assert command == "PC"
    assert payload["housecode"] == "A02"
    assert payload["index"] == 1
    assert payload["light_level"] == 55


def test_ps_decode_lighting_bank_status():
    data = "3" + "0" * 64
    frame = _wire("PS", data)
    command, payload = message.decode(frame)
    assert command == "PS"
    assert payload["bank"] == 3
    assert payload["statuses"] == [0] * 64


def test_rp_decode_elkrp_connected():
    frame = _wire("RP", "01")
    assert message.decode(frame) == ("RP", {"remote_programming_status": ElkRPStatus.CONNECTED})


def test_sd_decode_text_description_and_show_on_keypad_flag():
    desc_ch1 = "F"
    frame = _wire("SD", "00" + "001" + desc_ch1 + "ront Door      ")
    command, payload = message.decode(frame)
    assert command == "SD"
    assert payload == {
        "desc_type": 0,
        "unit": 0,
        "desc": "Front Door",
        "show_on_keypad": False,
    }


def test_sd_decode_show_on_keypad_high_bit_set():
    desc_ch1 = chr(0x80 | ord("F"))
    frame = _wire("SD", "00" + "001" + desc_ch1 + "ront Door      ")
    command, payload = message.decode(frame)
    assert command == "SD"
    assert payload["desc"] == "Front Door"
    assert payload["show_on_keypad"] is True


def test_tc_decode_task_change():
    frame = _wire("TC", "005")
    assert message.decode(frame) == ("TC", {"task": 4})


def test_ti_decode_passes_the_routed_string_through():
    """Rev 1.90's touchscreen-information route; this integration has no Elk
    Touchscreen consumer, so it is only ever passed through verbatim, not
    parsed further. Unverified: whether the real M1 wire format for this
    message includes the standard "00" reserved field before the checksum
    the way most replies do - this test only pins the current, documented
    "passed through verbatim" behavior against the standard frame shape.
    """
    frame = _wire("TI", "Hello touchscreen")
    assert message.decode(frame) == ("TI", {"routed_string": "Hello touchscreen00"})


def test_ua_decode_valid_user_code_areas():
    frame = _wire("UA", "001234" + "C3" + "00000000" + "4" + "0" + "F")
    assert message.decode(frame) == (
        "UA",
        {
            "user_code": 1234,
            "valid_areas": 0xC3,
            "diagnostic": "00000000",
            "user_code_length": 4,
            "user_code_type": 0,
            "temperature_units": "F",
        },
    )


def test_xk_decode_rtc_ip_communicator_test():
    frame = _wire("XK", "0102030405060708")
    assert message.decode(frame) == ("XK", {"real_time_clock": "0102030405060708"})


def test_zb_decode_bypass_state():
    frame = _wire("ZB", "0051")
    assert message.decode(frame) == ("ZB", {"zone_number": 4, "zone_bypassed": True})


def test_zc_decode_zone_change_status_nibble():
    frame = _wire("ZC", "0056")
    command, payload = message.decode(frame)
    assert command == "ZC"
    assert payload["zone_number"] == 4
    assert payload["zone_status"] == (ZoneLogicalStatus.TROUBLED, ZonePhysicalStatus.EOL)


def test_zd_decode_zone_definitions():
    data = "1" + "0" * 207
    frame = _wire("ZD", data)
    command, payload = message.decode(frame)
    assert command == "ZD"
    assert payload["zone_definitions"][0] == ZoneType.BURGLAR_ENTRY_EXIT_1
    assert payload["zone_definitions"][1] == ZoneType.DISABLED
    assert len(payload["zone_definitions"]) == 208


def test_zp_decode_zone_partitions():
    data = "1" + "2" * 207
    frame = _wire("ZP", data)
    command, payload = message.decode(frame)
    assert command == "ZP"
    assert payload["zone_partitions"][0] == 0
    assert payload["zone_partitions"][1] == 1
    assert len(payload["zone_partitions"]) == 208


def test_zs_decode_zone_statuses():
    data = "6" + "0" * 207
    frame = _wire("ZS", data)
    command, payload = message.decode(frame)
    assert command == "ZS"
    assert payload["zone_statuses"][0] == (ZoneLogicalStatus.TROUBLED, ZonePhysicalStatus.EOL)
    assert payload["zone_statuses"][1] == (ZoneLogicalStatus.NORMAL, ZonePhysicalStatus.UNCONFIGURED)
    assert len(payload["zone_statuses"]) == 208


def test_zv_decode_zone_analog_voltage():
    frame = _wire("ZV", "005123")
    assert message.decode(frame) == ("ZV", {"zone_number": 4, "zone_voltage": 12.3})


def test_tr_decode_thermostat_data_reply():
    """Field values match the spec's own worked-example prose (section 4.34):
    "Thermostat 01, data reply, Cool Mode, Hold temperature = False, Fan
    Auto, Current Temperature = 72, Heat Setpoint = 68, Cool Setpoint = 75,
    no humidity data"."""
    data = "01" + "2" + "0" + "0" + "72" + "68" + "75" + "00"
    frame = _wire("TR", data)
    assert message.decode(frame) == (
        "TR",
        {
            "thermostat_index": 0,
            "mode": ThermostatMode.COOL,
            "hold": False,
            "fan": ThermostatFan.AUTO,
            "current_temp": 72,
            "heat_setpoint": 68,
            "cool_setpoint": 75,
            "humidity": 0,
        },
    )


def test_pc_all_decode_aggregate_broadcast():
    """The `PC` "all lights in a house" aggregate form - a real gap in
    elkm1-lib 2.2.15 (see docs/decisions.md); this is also the exact frame
    this rewrite's own gate caught a field-offset bug on during the port
    (see the same decisions.md entry).
    """
    frame = _wire("PC", "A0002")
    assert message.decode(frame) == ("PC_ALL", {"house_index": 0, "aggregate_code": 2})


# --------------------------------------------------------------------------
# housecode helpers
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("index", "housecode"),
    [(0, "A01"), (15, "A16"), (16, "B01"), (255, "P16")],
)
def test_housecode_index_round_trip(index, housecode):
    assert message.index_to_housecode(index) == housecode
    assert message.housecode_to_index(housecode) == index


def test_housecode_to_index_rejects_invalid_housecode():
    with pytest.raises(ValueError, match="Invalid X10 housecode"):
        message.housecode_to_index("Q99")


def test_index_to_housecode_rejects_out_of_range_index():
    with pytest.raises(ValueError):
        message.index_to_housecode(256)


def test_get_elk_command_extracts_the_two_character_code():
    assert message.get_elk_command("06vn0056") == "vn"


def test_get_elk_command_returns_empty_for_too_short_a_line():
    assert message.get_elk_command("06v") == ""

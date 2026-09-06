"""Round-trip tests for record specs, encoding, bit access, and the account file."""

from __future__ import annotations

from pathlib import Path

import pytest

from elk_programmer.model import specs
from elk_programmer.model.account import Account
from elk_programmer.model.records import (
    blank_record,
    decode_record,
    encode_record,
    explain_flags,
    get_bit,
    record_from_columns,
    record_to_columns,
    set_bit,
)


@pytest.mark.parametrize("spec", specs.ALL_SPECS, ids=lambda s: s.name)
def test_spec_sizes_match_elkrp_structs(spec: specs.RecordSpec) -> None:
    expected = {
        "zone": 32,
        "area": 24,
        "keypad": 28,
        "user": 28,
        "output": 28,
        "task": 28,
        "telephone": 88,
        "global": 48,
        "lighting": 28,
        "voice_message": 12,
    }
    assert spec.size == expected[spec.name]


@pytest.mark.parametrize("spec", specs.ALL_SPECS, ids=lambda s: s.name)
def test_every_field_has_one_column_per_byte(spec: specs.RecordSpec) -> None:
    for f in (*spec.fields, *spec.extra):
        assert len(f.column_names()) == f.size, f.name


@pytest.mark.parametrize("spec", specs.ALL_SPECS, ids=lambda s: s.name)
def test_bytes_round_trip(spec: specs.RecordSpec) -> None:
    rec = blank_record(spec)
    for i, f in enumerate(spec.fields):
        if f.kind in (specs.Kind.U8,):
            rec[f.name] = (i * 37 + 5) % 256
        elif f.kind is specs.Kind.U16:
            rec[f.name] = (i * 1234) % 65536
        elif f.kind is specs.Kind.TEXT:
            rec[f.name] = f"Name {i}"[: f.length]
        elif f.kind in (specs.Kind.DIGITS, specs.Kind.CODE):
            rec[f.name] = ("3703703670" * 2)[: f.length]
        elif f.kind is specs.Kind.VOICE:
            rec[f.name] = [(i * 3 + k) % 500 for k in range(f.length)]
        else:
            rec[f.name] = bytes(range(f.length))
    raw = encode_record(spec, rec)
    assert len(raw) == spec.size
    decoded = decode_record(spec, raw)
    assert {k: v for k, v in decoded.items() if not k.endswith("Show")} == {
        f.name: rec[f.name] for f in spec.fields
    }
    assert encode_record(spec, decode_record(spec, raw)) == raw


def test_zone_bits_and_columns() -> None:
    rec = blank_record(specs.ZONE)
    rec["ZnFunction"] = 3
    rec["ZnZoneName"] = "Front Door"
    rec["ZnVoice"] = [21, 45, 0, 0, 0, 0]
    flag2 = specs.ZONE.field_by_name("ZnFlag2")
    hookup = next(b for b in flag2.bits if b.name == "hookup")
    area = next(b for b in flag2.bits if b.name == "area")
    rec["ZnFlag2"] = set_bit(set_bit(0, hookup, 1), area, 2)
    assert get_bit(rec["ZnFlag2"], area) == 2
    assert explain_flags(flag2, rec["ZnFlag2"]) == {
        "hookup": 1,
        "swinger_shutdown": 0,
        "area": 2,
        "silent_alarm": 0,
    }
    cols = record_to_columns(specs.ZONE, rec)
    assert cols["ZnZoneName1"] == ord("F")
    assert cols["ZnZoneName16"] == ord(" ")
    assert cols["ZnVoice1H"] == 0 and cols["ZnVoice1L"] == 21
    assert record_from_columns(specs.ZONE, cols)["ZnZoneName"] == "Front Door"


def test_set_bit_rejects_out_of_range() -> None:
    area = next(b for b in specs.ZONE.field_by_name("ZnFlag2").bits if b.name == "area")
    with pytest.raises(ValueError):
        set_bit(0, area, 8)


def test_user_code_digits_round_trip() -> None:
    rec = blank_record(specs.USER)
    rec["UCode"] = "3456"
    raw = encode_record(specs.USER, rec)
    # Reversed and zero filled at the high end, as ElkRP writes UCBytes.
    assert raw[:6] == bytes([6, 5, 4, 3, 0, 0])
    assert decode_record(specs.USER, raw)["UCode"] == "003456"


def test_account_json_round_trip(tmp_path: Path) -> None:
    acct = Account.blank("Bench panel")
    zone = acct.record("zone", 1)
    zone["ZnZoneName"] = "Front Door"
    zone["ZnFunction"] = 1
    acct.record("global", 1)["SysProgramCode"] = "172839"
    path = tmp_path / "bench.json"
    acct.save(path)
    back = Account.load(path)
    assert back.name == "Bench panel"
    assert back.record("zone", 1)["ZnZoneName"] == "Front Door"
    assert back.record("global", 1)["SysProgramCode"] == "172839"
    assert back.numbers("area") == list(range(1, 9))


def test_show_flag_survives_round_trip() -> None:
    rec = blank_record(specs.OUTPUT)
    rec["OPName"] = "Porch"
    rec["OPNameShow"] = True
    raw = encode_record(specs.OUTPUT, rec)
    assert raw[0] == ord("P") | 0x80
    back = decode_record(specs.OUTPUT, raw)
    assert back["OPName"] == "Porch" and back["OPNameShow"] is True
    cols = record_to_columns(specs.OUTPUT, rec)
    assert cols["OPName1"] == ord("P") | 0x80
    assert record_from_columns(specs.OUTPUT, cols)["OPNameShow"] is True

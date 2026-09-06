"""Bulk receive against a scripted panel that answers some items and not others."""

from __future__ import annotations

import asyncio

from elk_programmer.model import specs
from elk_programmer.model.account import Account
from elk_programmer.model.records import encode_record
from elk_programmer.protocol import messages as m
from elk_programmer.protocol.framing import Decoder, Kind, encode_frame
from elk_programmer.protocol.session import Session
from elk_programmer.protocol.sync import receive_all, send_record


class ScriptedPanel:
    """Answers reads for the records it holds; silent for anything else."""

    def __init__(self, records: dict[tuple[int, int, int], bytes]) -> None:
        self.records = records
        self.decoder = Decoder()
        self._inbox: asyncio.Queue[bytes] = asyncio.Queue()
        self.writes: list[bytes] = []

    async def write(self, data: bytes) -> None:
        for ev in self.decoder.feed(data):
            if ev.kind is not Kind.MESSAGE:
                continue
            op, sub, hi, lo = ev.body[:4]
            item = (hi << 8) | lo
            if op & 0x80:
                self.writes.append(ev.body)
                await self._inbox.put(encode_frame(bytes([op, sub, hi, lo])))
            elif (op, sub, item) in self.records:
                await self._inbox.put(
                    encode_frame(bytes([op, sub, hi, lo]) + self.records[(op, sub, item)])
                )

    async def read(self, timeout: float) -> bytes:
        try:
            return await asyncio.wait_for(self._inbox.get(), timeout)
        except TimeoutError:
            return b""

    async def close(self) -> None:
        pass


async def test_receive_all_merges_and_reports() -> None:
    area = {**{f.name: 0 for f in specs.AREA.fields}, "PName": "House", "PExit1": 60}
    zone = {
        **{f.name: 0 for f in specs.ZONE.fields},
        "ZnZoneName": "Front Door",
        "ZnFunction": 1,
        "ZnVoice": [0] * 6,
    }
    panel = ScriptedPanel(
        {
            (0x03, 0, 1): encode_record(specs.AREA, area),
            (0x05, 0, 1): encode_record(specs.ZONE, zone),
            (0x05, 0, 2): encode_record(specs.ZONE, {**zone, "ZnZoneName": "Garage"}),
        }
    )
    session = Session(panel)
    acct = Account.blank()
    acct.record("zone", 1)["ZnZoneName"] = "Old name"
    seen: list[str] = []
    report = await receive_all(
        session,
        acct,
        progress=lambda t, i, n, msg: seen.append(msg),
        tables=("area", "zone"),
        limits={"area": 2, "zone": 3},
    )
    assert report.read == {"area": 1, "zone": 2}
    assert report.unanswered == {"area": [2], "zone": [3]}
    assert report.changed == {"area": [1], "zone": [1, 2]}
    assert acct.record("area", 1)["PName"] == "House"
    assert acct.record("zone", 1)["ZnZoneName"] == "Front Door"
    assert acct.record("zone", 2)["ZnZoneName"] == "Garage"
    assert "Areas 2: no reply" in seen


async def test_send_record_writes_encoded_bytes() -> None:
    panel = ScriptedPanel({})
    session = Session(panel)
    acct = Account.blank()
    acct.record("area", 1)["PName"] = "House"
    reply = await send_record(session, acct, "area", 1)
    assert reply[:4] == bytes.fromhex("83000001")
    assert panel.writes[0][4:] == encode_record(specs.AREA, acct.record("area", 1))
    assert m.Record.AREA | 0x80 == 0x83

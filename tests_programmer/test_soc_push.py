"""Forwarding the audit chain to HA SOC: batches, acknowledgement, resume, refusal."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from elk_programmer.hass import HomeAssistant
from elk_programmer.security import AuditLog
from elk_programmer.soc_push import SocPusher


class FakeSoc:
    """Accepts records in order and answers like ha_soc.ingest_audit."""

    def __init__(self) -> None:
        self.head = 0
        self.received: list[int] = []
        self.secrets: set[str] = set()
        self.refuse: str | None = None
        self.calls = 0

    async def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        body = json.loads(request.content)
        assert request.url.path == "/core/api/services/ha_soc/ingest_audit"
        assert request.url.params.get("return_response") == "true"
        assert body["source"] == "elk_programmer"
        self.secrets.add(body["secret"])
        if self.refuse:
            return httpx.Response(
                200,
                json={
                    "service_response": {
                        "accepted": 0,
                        "last_seq": self.head or None,
                        "rejected": self.refuse,
                    }
                },
            )
        accepted = 0
        for record in body["records"]:
            if record["seq"] <= self.head:
                continue
            if record["seq"] > self.head + 1:
                return httpx.Response(
                    200,
                    json={
                        "service_response": {
                            "accepted": accepted,
                            "last_seq": self.head,
                            "rejected": "gap",
                        }
                    },
                )
            self.head = record["seq"]
            self.received.append(record["seq"])
            accepted += 1
        return httpx.Response(
            200,
            json={
                "service_response": {"accepted": accepted, "last_seq": self.head, "rejected": None}
            },
        )


def _write_audit(path: Path, n: int) -> AuditLog:
    log = AuditLog(path)
    for i in range(n):
        log.record(f"event_{i}", "user-1", "Alice", n=i)
    return log


async def test_pushes_in_batches_and_remembers_the_acknowledgement(tmp_path: Path) -> None:
    _write_audit(tmp_path / "audit.jsonl", 450)
    soc = FakeSoc()
    ha = HomeAssistant("tok", http_base="http://supervisor")
    ha.use_transport(httpx.MockTransport(soc.handle))
    pusher = SocPusher(ha, tmp_path, tmp_path / "audit.jsonl")
    result = await pusher.push()
    assert result == {"sent": 450, "last_seq": 450, "error": None}
    assert soc.calls == 3 and soc.received[-1] == 450
    assert json.loads((tmp_path / "soc_push.json").read_text())["last_seq"] == 450
    assert (tmp_path / "soc_secret").is_file() and len(soc.secrets) == 1
    # Nothing new: no call is made.
    assert await pusher.push() == {"sent": 0, "last_seq": 450, "error": None}
    assert soc.calls == 3
    # A restart resumes from the saved acknowledgement and only sends the new line.
    AuditLog(tmp_path / "audit.jsonl").record("later", "user-1", "Alice")
    again = SocPusher(ha, tmp_path, tmp_path / "audit.jsonl")
    assert again.last_seq == 450
    assert (await again.push())["sent"] == 1


async def test_resumes_from_soc_head_after_a_gap(tmp_path: Path) -> None:
    _write_audit(tmp_path / "audit.jsonl", 10)
    soc = FakeSoc()
    soc.head = 4
    ha = HomeAssistant("tok", http_base="http://supervisor")
    ha.use_transport(httpx.MockTransport(soc.handle))
    pusher = SocPusher(ha, tmp_path, tmp_path / "audit.jsonl")
    pusher.last_seq = 7  # our record says more was acknowledged than HA SOC holds
    result = await pusher.push()
    assert result == {"sent": 6, "last_seq": 10, "error": None}
    assert soc.received == [5, 6, 7, 8, 9, 10]


async def test_refusal_stops_without_advancing(tmp_path: Path) -> None:
    _write_audit(tmp_path / "audit.jsonl", 3)
    soc = FakeSoc()
    soc.refuse = "bad_secret"
    ha = HomeAssistant("tok", http_base="http://supervisor")
    ha.use_transport(httpx.MockTransport(soc.handle))
    pusher = SocPusher(ha, tmp_path, tmp_path / "audit.jsonl")
    result = await pusher.push()
    assert result["error"] == "bad_secret" and result["sent"] == 0
    assert pusher.last_seq == 0 and pusher.last_error == "bad_secret"


async def test_transport_error_is_reported_not_raised(tmp_path: Path) -> None:
    _write_audit(tmp_path / "audit.jsonl", 1)

    async def down(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    ha = HomeAssistant("tok", http_base="http://supervisor")
    ha.use_transport(httpx.MockTransport(down))
    pusher = SocPusher(ha, tmp_path, tmp_path / "audit.jsonl")
    result = await pusher.push()
    assert result["sent"] == 0 and "503" in str(result["error"])

"""Forward the app's audit chain to HA SOC's ``ha_soc.ingest_audit`` service.

Every line of ``audit.jsonl`` is one record whose hash commits to the line
before it. HA SOC verifies that chain on receipt and keeps the last record
it accepted per source, so this client only has to send what HA SOC has
not yet acknowledged, in order, and resume from where HA SOC says it is.
The line number is the sequence number; it is transport ordering, not part
of the hash. The per-source secret is generated once, kept under the data
directory with restrictive permissions, and pinned by HA SOC on the first
accepted call. See docs/programmer/app.md, "Audit forwarding to HA SOC".
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
from pathlib import Path
from typing import Any

from .hass import HomeAssistant, HomeAssistantError

_LOGGER = logging.getLogger(__name__)

SOURCE = "elk_programmer"
BATCH_MAX = 200
SECRET_BYTES = 32


class SocPusher:
    """Sends unacknowledged audit lines to HA SOC; safe to call often."""

    def __init__(self, hass: HomeAssistant, data_dir: Path, audit_path: Path) -> None:
        self._hass = hass
        self._audit_path = audit_path
        self._state_path = data_dir / "soc_push.json"
        self._secret_path = data_dir / "soc_secret"
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[dict[str, Any]] | None = None
        self.last_seq = 0
        self.last_error: str | None = None
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
            self.last_seq = int(data.get("last_seq", 0))
        except (OSError, ValueError):
            self.last_seq = 0

    def _save(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(json.dumps({"last_seq": self.last_seq}), encoding="utf-8")

    def secret(self) -> str:
        if self._secret_path.is_file():
            return self._secret_path.read_text(encoding="utf-8").strip()
        value = secrets.token_hex(SECRET_BYTES)
        self._secret_path.parent.mkdir(parents=True, exist_ok=True)
        self._secret_path.write_text(value, encoding="utf-8")
        os.chmod(self._secret_path, 0o600)
        return value

    def _pending(self) -> list[dict[str, Any]]:
        """Records after ``last_seq`` with their line numbers as ``seq``."""
        if not self._audit_path.is_file():
            return []
        out: list[dict[str, Any]] = []
        with self._audit_path.open("r", encoding="utf-8") as fh:
            for seq, line in enumerate(fh, start=1):
                if seq <= self.last_seq or not line.strip():
                    continue
                entry = json.loads(line)
                out.append(
                    {
                        "seq": seq,
                        "time": entry["time"],
                        "event": entry["event"],
                        "user_id": entry.get("user_id") or None,
                        "user_name": entry.get("user_name") or None,
                        "details": entry.get("details") or {},
                        "previous": entry.get("previous", ""),
                        "hash": entry["hash"],
                    }
                )
                if len(out) >= BATCH_MAX:
                    break
        return out

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def schedule(self) -> None:
        """Start a push unless one is already running; never blocks the caller."""
        if self.running:
            return
        self._task = asyncio.create_task(self.push())

    async def push(self) -> dict[str, Any]:
        """Send pending records until HA SOC is caught up or refuses."""
        async with self._lock:
            sent_total = 0
            while True:
                batch = self._pending()
                if not batch:
                    self.last_error = None
                    return {"sent": sent_total, "last_seq": self.last_seq, "error": None}
                try:
                    reply = await self._hass.call_service(
                        "ha_soc",
                        "ingest_audit",
                        {"source": SOURCE, "secret": self.secret(), "records": batch},
                        return_response=True,
                    )
                except HomeAssistantError as err:
                    self.last_error = str(err)
                    _LOGGER.warning("audit forwarding to HA SOC failed: %s", err)
                    return {"sent": sent_total, "last_seq": self.last_seq, "error": str(err)}
                response = (reply or {}).get("service_response", reply) or {}
                accepted = int(response.get("accepted") or 0)
                acked = response.get("last_seq")
                sent_total += accepted
                if isinstance(acked, int) and acked > self.last_seq:
                    self.last_seq = acked
                    self._save()
                rejected = response.get("rejected")
                if rejected == "gap" and isinstance(acked, int):
                    # HA SOC holds fewer records than we do; resume from its head.
                    if acked < self.last_seq:
                        self.last_seq = acked
                        self._save()
                    continue
                if rejected:
                    self.last_error = str(rejected)
                    _LOGGER.error("HA SOC refused audit records: %s", rejected)
                    return {"sent": sent_total, "last_seq": self.last_seq, "error": str(rejected)}
                if accepted == 0:
                    return {"sent": sent_total, "last_seq": self.last_seq, "error": None}

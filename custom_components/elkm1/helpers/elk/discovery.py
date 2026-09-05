"""UDP discovery of ELK-M1XEP network interfaces (port 2362, "XEPID" probe)."""

from __future__ import annotations

import asyncio
import logging
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from struct import unpack

_LOGGER = logging.getLogger(__name__)


@dataclass
class ElkSystem:
    """One discovered M1XEP: its MAC, IP, and port."""

    mac_address: str
    ip_address: str
    port: int


def create_udp_socket(discovery_port: int) -> socket.socket:
    """Create the broadcast-capable UDP socket used to send discovery probes."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind(("", 0))
    sock.setblocking(False)
    return sock


class ELKDiscovery(asyncio.DatagramProtocol):
    """Datagram protocol that forwards every received packet to a callback."""

    def __init__(
        self, destination: tuple[str, int], on_response: Callable[[bytes, tuple[str, int]], None]
    ) -> None:
        self.transport = None
        self.destination = destination
        self.on_response = on_response

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        """Forward a received packet."""
        self.on_response(data, addr)

    def error_received(self, exc: Exception | None) -> None:
        """Log a socket-level error."""
        _LOGGER.error("ELKDiscovery error: %s", exc)

    def connection_lost(self, exc: Exception | None) -> None:
        """No cleanup needed on close."""


def _decode_data(raw_response: bytes) -> ElkSystem:
    """Decode an M1XEP discovery response packet into (mac, ip, port)."""
    remain = raw_response[5:]
    data = remain[:14]
    (mac1, mac2, mac3, mac4, mac5, mac6, ipv4_1, ipv4_2, ipv4_3, ipv4_4, port, _) = unpack(
        "!6B4BHH", data
    )
    mac_address = ":".join(
        format(val, "02x").upper().zfill(2) for val in (mac1, mac2, mac3, mac4, mac5, mac6)
    )
    ip_address = f"{ipv4_1}.{ipv4_2}.{ipv4_3}.{ipv4_4}"
    return ElkSystem(mac_address, ip_address, port)


class AIOELKDiscovery:
    """UDP broadcast scanner for M1XEP interfaces on port 2362."""

    DISCOVERY_PORT = 2362
    BROADCAST_FREQUENCY = 3
    DISCOVER_MESSAGE = b"XEPID"
    BROADCAST_ADDRESS = "<broadcast>"

    def __init__(self) -> None:
        self.found_devices: list[ElkSystem] = []

    def _destination_from_address(self, address: str | None) -> tuple[str, int]:
        return (address or self.BROADCAST_ADDRESS, self.DISCOVERY_PORT)

    def _process_response(
        self,
        data: bytes | None,
        from_address: tuple[str, int],
        address: str | None,
        response_list: dict[tuple[str, int], ElkSystem],
    ) -> bool:
        """Decode one response; return True if this was the directed address we wanted."""
        if data is None or data == self.DISCOVER_MESSAGE or not data.startswith(b"M1XEP"):
            return False
        try:
            response_list[from_address] = _decode_data(data)
        except Exception as ex:
            _LOGGER.warning("Failed to decode response from %s: %s", from_address, ex)
            return False
        return from_address[0] == address

    async def _async_run_scan(
        self,
        transport: asyncio.DatagramTransport,
        destination: tuple[str, int],
        timeout: int,
        found_all_future: asyncio.Future[bool],
    ) -> None:
        _LOGGER.debug("discover: %s => %s", destination, self.DISCOVER_MESSAGE)
        transport.sendto(self.DISCOVER_MESSAGE, destination)
        quit_time = time.monotonic() + timeout
        remain_time = float(timeout)
        while True:
            time_out = min(remain_time, timeout / self.BROADCAST_FREQUENCY)
            if time_out <= 0:
                return
            try:
                await asyncio.wait_for(asyncio.shield(found_all_future), timeout=time_out)
            except TimeoutError:
                if time.monotonic() >= quit_time:
                    return
                _LOGGER.debug("discover: %s => %s", destination, self.DISCOVER_MESSAGE)
                transport.sendto(self.DISCOVER_MESSAGE, destination)
            else:
                return
            remain_time = quit_time - time.monotonic()

    async def async_scan(self, timeout: int = 10, address: str | None = None) -> list[ElkSystem]:
        """Broadcast (or directly query one address) and return every M1XEP found."""
        sock = create_udp_socket(self.DISCOVERY_PORT)
        destination = self._destination_from_address(address)
        found_all_future: asyncio.Future[bool] = asyncio.Future()
        response_list: dict[tuple[str, int], ElkSystem] = {}

        def _on_response(data: bytes, addr: tuple[str, int]) -> None:
            _LOGGER.debug("discover: %s <= %s", addr, data)
            if self._process_response(data, addr, address, response_list):
                found_all_future.set_result(True)

        transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(
            lambda: ELKDiscovery(destination=destination, on_response=_on_response),
            sock=sock,
        )
        try:
            await self._async_run_scan(transport, destination, timeout, found_all_future)
        finally:
            transport.close()

        self.found_devices = list(response_list.values())
        return self.found_devices

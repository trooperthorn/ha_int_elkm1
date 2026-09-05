"""Unit tests for helpers/elk/discovery.py's UDP M1XEP discovery scanner.
Closes a gap left by the 2026-09-05 elkm1-lib removal (see docs/decisions.md):
`test_config_flow.py` only imports the `ElkSystem` dataclass, never exercises
discovery itself.
"""

from __future__ import annotations

import asyncio
import socket
from struct import pack

from custom_components.elkm1.helpers.elk.discovery import (
    AIOELKDiscovery,
    ELKDiscovery,
    ElkSystem,
    _decode_data,
    create_udp_socket,
)


def _m1xep_packet(mac: tuple[int, ...], ip: tuple[int, ...], port: int) -> bytes:
    """Build a raw M1XEP discovery-reply packet matching `_decode_data`'s layout."""
    header = b"M1XEP"  # 5 bytes, sliced off by `_decode_data`'s `raw_response[5:]`
    body = pack("!6B4BHH", *mac, *ip, port, 0)
    return header + body


# --------------------------------------------------------------------------
# create_udp_socket
# --------------------------------------------------------------------------


def test_create_udp_socket_is_broadcast_capable_and_nonblocking(socket_enabled):
    sock = create_udp_socket(2362)
    try:
        assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST) != 0
        assert sock.type == socket.SOCK_DGRAM
        assert sock.getblocking() is False
    finally:
        sock.close()


# --------------------------------------------------------------------------
# _decode_data
# --------------------------------------------------------------------------


def test_decode_data_extracts_mac_ip_and_port():
    packet = _m1xep_packet(
        mac=(0x00, 0x40, 0x9D, 0x01, 0x02, 0x03), ip=(192, 168, 1, 50), port=2101
    )
    system = _decode_data(packet)
    assert system == ElkSystem("00:40:9D:01:02:03", "192.168.1.50", 2101)


def test_decode_data_zero_pads_single_digit_mac_bytes():
    packet = _m1xep_packet(mac=(0, 1, 2, 3, 4, 5), ip=(10, 0, 0, 1), port=2101)
    system = _decode_data(packet)
    assert system.mac_address == "00:01:02:03:04:05"


# --------------------------------------------------------------------------
# ELKDiscovery datagram protocol
# --------------------------------------------------------------------------


def test_elk_discovery_forwards_received_datagrams():
    received = []
    protocol = ELKDiscovery(("1.2.3.4", 2362), lambda data, addr: received.append((data, addr)))

    protocol.datagram_received(b"M1XEPdata", ("1.2.3.4", 2362))

    assert received == [(b"M1XEPdata", ("1.2.3.4", 2362))]


def test_elk_discovery_logs_but_does_not_raise_on_socket_error():
    protocol = ELKDiscovery(("1.2.3.4", 2362), lambda data, addr: None)
    protocol.error_received(OSError("network unreachable"))  # must not raise


def test_elk_discovery_connection_lost_is_a_no_op():
    protocol = ELKDiscovery(("1.2.3.4", 2362), lambda data, addr: None)
    protocol.connection_lost(None)  # must not raise


# --------------------------------------------------------------------------
# AIOELKDiscovery: destination selection and response classification
# --------------------------------------------------------------------------


def test_destination_defaults_to_broadcast_when_no_address_given():
    scanner = AIOELKDiscovery()
    assert scanner._destination_from_address(None) == ("<broadcast>", 2362)


def test_destination_uses_the_given_address():
    scanner = AIOELKDiscovery()
    assert scanner._destination_from_address("192.168.1.50") == ("192.168.1.50", 2362)


def test_process_response_ignores_none_data():
    scanner = AIOELKDiscovery()
    response_list: dict = {}
    assert scanner._process_response(None, ("1.2.3.4", 2362), None, response_list) is False
    assert response_list == {}


def test_process_response_ignores_the_echoed_probe_message():
    scanner = AIOELKDiscovery()
    response_list: dict = {}
    result = scanner._process_response(
        scanner.DISCOVER_MESSAGE, ("1.2.3.4", 2362), None, response_list
    )
    assert result is False
    assert response_list == {}


def test_process_response_ignores_data_not_prefixed_m1xep():
    scanner = AIOELKDiscovery()
    response_list: dict = {}
    result = scanner._process_response(b"garbage", ("1.2.3.4", 2362), None, response_list)
    assert result is False
    assert response_list == {}


def test_process_response_records_a_valid_reply_and_signals_broadcast_scan_incomplete():
    """During an undirected (broadcast) scan, `address` is None, so a valid
    reply is recorded but the scan is never told "found the one I wanted" -
    it keeps listening for the full timeout to collect every panel."""
    scanner = AIOELKDiscovery()
    response_list: dict = {}
    packet = _m1xep_packet(mac=(0, 1, 2, 3, 4, 5), ip=(10, 0, 0, 1), port=2101)
    from_addr = ("10.0.0.1", 2362)

    result = scanner._process_response(packet, from_addr, None, response_list)

    assert result is False
    assert response_list[from_addr] == ElkSystem("00:01:02:03:04:05", "10.0.0.1", 2101)


def test_process_response_signals_complete_when_the_directed_address_replies():
    scanner = AIOELKDiscovery()
    response_list: dict = {}
    packet = _m1xep_packet(mac=(0, 1, 2, 3, 4, 5), ip=(10, 0, 0, 1), port=2101)
    from_addr = ("10.0.0.1", 2362)

    result = scanner._process_response(packet, from_addr, "10.0.0.1", response_list)

    assert result is True


def test_process_response_records_but_does_not_complete_for_an_unrelated_reply_during_a_directed_scan():
    scanner = AIOELKDiscovery()
    response_list: dict = {}
    packet = _m1xep_packet(mac=(0, 1, 2, 3, 4, 5), ip=(10, 0, 0, 2), port=2101)
    from_addr = ("10.0.0.2", 2362)

    result = scanner._process_response(packet, from_addr, "10.0.0.1", response_list)

    assert result is False
    assert from_addr in response_list


def test_process_response_handles_a_malformed_m1xep_packet_without_raising():
    scanner = AIOELKDiscovery()
    response_list: dict = {}
    malformed = b"M1XEP" + b"\x00" * 3  # too short for the expected struct layout

    result = scanner._process_response(malformed, ("1.2.3.4", 2362), None, response_list)

    assert result is False
    assert response_list == {}


# --------------------------------------------------------------------------
# async_scan: a real loopback round-trip against a fake M1XEP responder
# --------------------------------------------------------------------------


class _FakeM1XEPResponder(asyncio.DatagramProtocol):
    """Answers every "XEPID" probe with a canned M1XEP reply, like a real panel."""

    def __init__(self, reply: bytes) -> None:
        self.transport: asyncio.DatagramTransport | None = None
        self.reply = reply

    def connection_made(self, transport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if data == AIOELKDiscovery.DISCOVER_MESSAGE and self.transport is not None:
            self.transport.sendto(self.reply, addr)


async def test_async_scan_resends_the_probe_and_times_out_with_no_responder(socket_enabled):
    """A broadcast scan with nothing answering must resend the probe at
    `BROADCAST_FREQUENCY` intervals (the `_async_run_scan` retry branch) and
    return an empty list once the full timeout elapses, rather than hanging
    or raising."""
    scanner = AIOELKDiscovery()
    scanner.DISCOVERY_PORT = 25999  # nothing listens here

    found = await scanner.async_scan(timeout=1, address="127.0.0.1")

    assert found == []


async def test_async_scan_finds_a_directed_panel_over_real_loopback_udp(socket_enabled):
    reply = _m1xep_packet(mac=(0, 1, 2, 3, 4, 5), ip=(127, 0, 0, 1), port=2101)
    responder_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    responder_sock.bind(("127.0.0.1", 0))
    responder_port = responder_sock.getsockname()[1]

    loop = asyncio.get_running_loop()
    transport, _protocol = await loop.create_datagram_endpoint(
        lambda: _FakeM1XEPResponder(reply), sock=responder_sock
    )
    try:
        scanner = AIOELKDiscovery()
        scanner.DISCOVERY_PORT = responder_port
        found = await scanner.async_scan(timeout=2, address="127.0.0.1")

        assert found == [ElkSystem("00:01:02:03:04:05", "127.0.0.1", 2101)]
    finally:
        transport.close()

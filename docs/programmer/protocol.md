# The RP programming protocol, as reconstructed from ElkRP 2.0.41

Elk Products never published the protocol ElkRP uses to read and write an
Elk-M1 Gold panel's EEPROM configuration. Everything in this document was
recovered from the decompiled ElkRP assemblies under
`~/workspace/ElkRP_decompiled/M1G2/M1G/` (the M1 Gold module) and the COM
interop wrapper for `ElkComm2.dll`. File and line citations refer to that
tree. Nothing here has yet been exercised against a real panel; the
"Verified" column says which facts are fully determined by the source and
which are inferred. A live qualification pass against a bench panel is the
next step, and `docs/live_qualification.md` will record it.

This protocol is unrelated to the RS-232 ASCII automation protocol that the
`ha_int_elkm1` integration speaks. ElkRP contains no ASCII command literals
at all.

## Framing

| Rule | Value | Verified | Source |
| --- | --- | --- | --- |
| Frame | `DLE STX body DLE ETX CRC-hi CRC-lo` (`10 02 ... 10 03 hh ll`) | Yes | USBCom.cs 149-172, TLS.cs 340-374 |
| Byte stuffing | A `0x10` inside the body is sent twice; the duplicate is not in the CRC | Yes | USBCom.cs 158-167 |
| Length field | None; the frame ends at `DLE ETX` | Yes | USBCom.cs |
| CRC | CRC-16, polynomial 0x1021, initial 0x0000, no reflection, no final XOR (CRC-16/XMODEM), over the unstuffed body only | Yes for the managed transports; the native serial DLL is assumed identical | USBCom.cs 475-498 |
| ACK | `10 06`, no body, no CRC | Yes | USBCom.cs 349-356 |
| NAK | `10 15` | Yes | USBCom.cs 357-364 |
| Debug stream | A body whose first byte is `0xFF` is panel debug output; discard it | Yes | USBCom.cs 374-377, 440-446 |
| USB (C1M1) wrapper | The framed bytes are sent as JSON text `{"RP":[16,2,...]}` | Yes | USBCom.cs 173-176 |

Known frames, useful as test vectors:

| Purpose | Frame |
| --- | --- |
| Keepalive | `10 02 7F 00 00 A5 10 03 73 D4` |
| Disconnect | `10 02 7F 01 00 A5 10 03 44 E4` |
| Read Area 1 | `10 02 03 00 00 01 10 03 8B FD` |

`elk_programmer.protocol.framing` implements this and `tests/test_protocol.py`
checks those three vectors.

## Request and reply shape

Every request is four header bytes followed by an optional payload:

```
opcode  sub  item-hi  item-lo  [payload]
```

Replies repeat the opcode in byte 0. For record reads the record bytes start at
byte 4. Bytes 1 to 3 of a reply are never inspected by ElkRP for record reads,
so their meaning is unverified; by analogy with the request they echo the item
number. A write reply echoes the write opcode; it is not a bare ACK. Control
writes with opcode `0xFF` expect a bare ACK instead.

Buffers are 2048 bytes on both sides (M1GControl.cs 4270, 4274).

## Retry and timeout

| Rule | Value | Source |
| --- | --- | --- |
| Default attempts, timeout | 4, 800 ms | M1Fns.cs 1275 |
| Timeout scaling | doubled below 115200 baud, doubled again below 2400 baud; times 3 on ElkLink Ethernet, times 5 on ElkLink cellular | M1Fns.cs 1332-1350 |
| Success | a good frame whose byte 0 equals the expected opcode, or an ACK when an ACK was expected | M1Fns.cs 1485-1489, 1553-1661 |
| Panel hang-up | any received frame starting `7F 01` ends the session | M1Fns.cs 1634-1646 |

## Session

| Step | Bytes | Expect | Attempts, timeout | Source |
| --- | --- | --- | --- | --- |
| Login | `7F 00 00 01` then the six RP access code digits, one per byte, last digit first, short codes left padded with 0 | `7F` | 4, 1600 ms | M1Fns.cs 6700-6762, 6884-6889 |
| Login, secure network | the plain login plus 16 bytes of AES-128-CBC ciphertext (zero IV, no padding, a key embedded in ElkRP) over a random byte, the serial number nibbles, a random byte, and the code digits forward | `7F` | same | M1Fns.cs 6764-6853, 12379-12401 |
| Keepalive | `7F 00 00 A5` every 15 s of silence | `7F` | 2, 5000 ms | MiscStuff.cs 2673-2846 |
| Disconnect | `7F 01 00 A5` | `7F` | 2, 500 ms | M1Fns.cs 3311-3341 |
| Change RP code | `7F 00 00 05` then six digits | `7F` | | M1Fns.cs 4291-4303 |

Login reply layout as ElkRP reads it (byte offsets in the body):

| Offset | Meaning | Source |
| --- | --- | --- |
| 1 | non-zero means the session is not usable; exact meaning unverified | M1Fns.cs 6912-6916 |
| 4 to 6 | firmware version major, mid, minor; major below 4 means the bootloader is running | M1Fns.cs 7011, 6939-6944 |
| 8 to 11 | serial number, one hex nibble per byte | M1Fns.cs 7215-7230 |
| 12 to 13 | hardware version | M1Fns.cs 7280-7283 |
| 14 to 16 | boot version | M1Fns.cs 7280-7283 |
| 19 to 21 | event list revision | M1Fns.cs 7481 |
| 22 to 24 | minimum ElkRP version the panel demands | M1Fns.cs 7292-7327 |

A rejected RP code has no distinct reply in ElkRP's code paths; every failure
is a missing or short reply or a serial number mismatch. Whether the panel
stays silent on a bad code is unverified.

The secure-network login variant is not implemented in this repository: the
hardcoded key is a shared secret embedded in every copy of ElkRP, and a panel
on a trusted network segment can be reached through the non-secure port. See
`docs/security.md`.

## Configuration records

A record type is selected by opcode and the instance by the 16-bit item number
in header bytes 2 and 3. Reading uses the base opcode; writing uses the base
opcode plus 0x80. There is no EEPROM address on the wire for configuration.

| Record | Read | Write | Item | Size | Mapped in this repository | Source |
| --- | --- | --- | --- | --- | --- | --- |
| User code | 0x01 | 0x81 | byte 3 = user | 28 | Yes | User_Codes.cs 7494-7506, 8069-8081 |
| Output and task text | 0x02 | 0x82 | byte 1 = text class, bytes 2 to 3 = index | | No, class byte untraced | Outputs.cs 3788-3796; Tasks.cs 7512-7520 |
| Area | 0x03 | 0x83 | byte 3 = area | 24 | Yes | Area_Definitions.cs 5795-5836, 6305-6350 |
| Keypad | 0x04 | 0x84 | byte 1 = page 0 or 1 | | No, page split untraced | Keypad_Definitions.cs 10442-10450, 11098-11106 |
| Zone | 0x05 | 0x85 | bytes 2 to 3 = zone | 32 | Yes | Zone_Definitions.cs 9726-9734, 10414-10422 |
| Globals | 0x07 | 0x87 | byte 3 = block | | No, blocks untraced | Globals_Data.cs 7969-7981, 8401-8413 |
| Telephone | 0x08 | 0x88 | byte 3 = index | 88 | Yes | Telephone_Numbers.cs 8630-8638, 9222-9230 |
| Report codes | 0x09 to 0x0C, 0x10 | plus 0x80 | varies | | No | Report_Codes.cs |
| Voice message | 0x0D | 0x8D | byte 1 = page, bytes 2 to 3 = index | | No | Voice_Messages.cs 3432-3440 |
| Lighting | 0x0E | 0x8E | byte 1 = page | | No | X10_Outputs.cs 4587-4591 |
| Wireless | 0x0F | 0x8F | byte 1 = sub-op | | No | Wireless_Zones.cs 6668-6680 |
| Rules | 0x79 | 0xF9 | bytes 2 to 3 = packet | | No | WhenThen.cs 9515-9527, 10329-10341 |

The "Mapped" column is what `elk_programmer.protocol.panel` will send. A
table is mapped only when its send and receive path resolves to one opcode,
one item encoding, and one fixed size in the source; the GUI refuses to send
anything else and says why.

Record byte layouts are in `docs/programmer/records.md`.

## Consistency checks

`7E <record type> <item-hi> <item-lo>` returns, at reply bytes 4 and 5, the
16-bit CRC the panel holds for that record. ElkRP compares it with the
`ModCRC` and `UDCRC` columns it stores per record to detect drift between its
database and the panel (Area_Definitions.cs 7629-7670). `7E 7F 00 00` returns
56 group CRCs at bytes 4 to 115, covering every table (M1Fns.cs 8699-8990).

## Other commands on the same channel

| Bytes | Purpose | Source |
| --- | --- | --- |
| `7F 00 00 03`, `FF 00 00 03` plus BCD time | read and set the clock | SetTime.cs 1144-1147, 700-751 |
| `7F 00 00 04` | system status used for active item discovery | M1Fns.cs 8435-8447 |
| `7F 00 00 0C`, `FF 00 00 0C v` | read and write the anti-takeover value | Globals_Data.cs 8059-8079, 8487-8517 |
| `7F b 00 0D` | change baud, code 1 to 9 | M1Fns.cs 4753-4788 |
| `7F 00 00 11` | version query | SystemVers.cs 835-838 |
| `7F 00 AA 55` | default the whole control (ElkRP then waits about 75 s) | M1Fns.cs 11769-11794 |
| `7F 00 55 AA` | enter flash mode | PgmFlash.cs 4583-4595 |
| `7B ...` | event log read | ReceiveLog.cs 1340-1352, 1550-1562 |
| `7C 00 type num` | bus device version query | M1Fns.cs 9008-9020 |
| `75 sub` | M1XEP passthrough | XEPConfig.cs |
| `28`, `FC 01/02/03` | firmware programming | PgmFlash.cs |

Defaulting, flash mode, firmware programming, and the manufacturing commands
are deliberately not implemented. They are irreversible or can brick a panel.

## Unverified

- Reply header bytes 1 to 3 for record reads.
- The meaning of byte 1 in the `7F` login reply beyond "non-zero is bad".
- Whether a wrong RP code produces any reply.
- That the native serial DLL's CRC matches the managed transports.
- Record sizes for the unmapped tables.

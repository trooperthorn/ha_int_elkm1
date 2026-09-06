# Record layouts

Each Elk-M1 Gold programming record is a fixed run of bytes. ElkRP stores those
bytes one column per byte in its Jet database (`ElkAccts2.mdb`), and the
column order is the byte order, so the database schema doubles as the record
layout. The structures in `M1CtlHdr.cs` carry the same fields but no layout
attributes, so sizes there are estimates; the database columns are what ElkRP
actually round-trips and are the layout used by `elk_programmer.model.specs`.

Bit names come from the private `*Bits` enums in each ElkRP form. Where an enum
names only some bits, the unnamed bits are left unlabelled and are preserved as
part of the byte. Widths of multi-bit groups are inferred from the gaps between
named bits and are marked unverified.

## Zone, 32 bytes, 208 records (`ZoneDefinitions`, Zone_Definitions.cs)

| Offset | Field | Meaning |
| --- | --- | --- |
| 0 | ZnFunction | definition, 0 to 36, see the `ZoneDefEnum` order below |
| 1 | ZnFlag1 | bit 0 bypassable, 1 activity monitor, 2 fast response, 3 force arm, 4 chime, 5 cross zoned, 6 abort, 7 listen in |
| 2 | ZnFlag2 | bits 0 to 2 hookup, bit 3 swinger shutdown, bits 4 to 6 area (0 = Area 1), bit 7 silent alarm |
| 3 | ZnNotUsed1 | |
| 4 to 19 | ZnZoneName | 16 ASCII characters, space padded |
| 20 to 31 | ZnVoice | six 16-bit word ids, high byte first |

Report codes for a zone (alarm, restoral, bypass, trouble) are separate
columns in the same table and travel in the report code records, not in the
zone record.

Definition order (`ZoneDefEnum`, M1CtlHdr.cs 1546): Disabled, Burglar Entry/Exit 1,
Burglar Entry/Exit 2, Burglar Perimeter Instant, Burglar Interior, Burglar
Interior Follower, Burglar Interior Night, Burglar Interior Night Delay,
Burglar 24 Hour, Burglar Box Tamper, Fire Alarm, Fire Verified, Fire
Supervisory, Aux Alarm 1, Aux Alarm 2, Keyfob, Non Alarm, Carbon Monoxide,
Emergency, Freeze, Gas, Heat, Medical, Police, Police No Indication, Water,
Key Momentary Arm/Disarm, Key Momentary Arm Away, Key Momentary Arm Stay, Key
Momentary Disarm, Key On/Off, Mute Audibles, Power Supervisory, Temperature,
Analog, Phone Key, Intercom Key.

Hookup order (`HWDefEnum`, M1CtlHdr.cs 1588): EOL supervised, normally closed,
normally open, supervised short, supervised open, 4-wire smoke, 2-wire smoke
on zone 16, analog. That the three low bits of ZnFlag2 hold this enum is
inferred from the bit gap and is unverified.

## Area, 24 bytes, 8 records (`AreaDefinitions`, Area_Definitions.cs)

| Offset | Field | Meaning |
| --- | --- | --- |
| 0 to 15 | PName | name |
| 16 to 19 | PExit1, PEntrance1, PExit2, PEntrance2 | delays in seconds |
| 20 | PFlags1 | bit 0 quick arm, bits 1 to 2 closing ring-back, bit 4 auto interior off, bit 6 STAY key scroll |
| 21 | PFlags2 | bit 3 show Night Instant, 4 show Night, 5 show Stay Instant, 6 show Stay, 7 double press to arm |
| 22 | PArmTimeWindow | |
| 23 | PNotUsed | |

Report code columns for the area follow in the database but not in the record.

## Keypad, 28 bytes, 16 records (`KeypadDefinitions`, Keypad_Definitions.cs)

| Offset | Field | Meaning |
| --- | --- | --- |
| 0 | KeypadAreas | area, 0 based |
| 1 | KPFlags1 | bit 2 zone response, 3 temperature, 4 date and time, 5 area name |
| 2 | KPFlags2 | bits 0 to 5 F1 to F6 invert light |
| 3 | KPFlags3 | bit 1 bypass key requires code, bits 2 to 7 named F, E, D, C, B, A in the enum; mapped here to F6 down to F1, unverified |
| 4 | KPFlags4 | bit 0 backlight, bit 4 key tone (widths unverified) |
| 5 | KPFlags5 | bit 1 silence LED, 2 silence chime, 3 silence exit, 4 silence entry, bit 5 beep volume |
| 6 to 21 | KeypadName | name |
| 22 | KeyLEDState | |
| 23 | KPFlags6 | bits 0 to 5 F1 to F6 blink light |
| 24 | KPFlags7 | bits 0 to 5 F1 to F6 single key press |
| 25 to 27 | NotUsed1 to 3 | |

Function key task bindings, light events, key names, and the hardware version
are further columns in the same table; they travel in the second keypad page,
which is not yet mapped on the wire.

## User code, 28 bytes, 199 records (`UserCodes`, User_Codes.cs)

| Offset | Field | Meaning |
| --- | --- | --- |
| 0 to 5 | UCode | code digits, one per byte, stored reversed: the first typed digit is at the highest used index and unused high bytes are 0 (User_Codes.cs 11446, 10730) |
| 6 | UCFlags1 | bit 1 automation, 2 master, 4 access, 5 bypass, 6 disarm, 7 arm |
| 7 | UCFlags2 | bit 0 duress |
| 8 | UCPartition | area bitmask, bit 0 = Area 1 |
| 9 to 24 | UCName | name |
| 25 | UCFlags3 | bit 7 temporary code |
| 26 to 27 | UCNotUsed1 to 2 | |

The editor shows codes as six digits; the panel's global "six digit codes"
option decides how many are meaningful.

## Output and task, 28 bytes (`POutputs` 208 records, `Tasks` 32 records)

16 name characters followed by six voice word ids. On the wire these travel as
text class records (opcode 0x02) whose class byte has not been traced yet.

## Telephone number, 88 bytes, 8 records (`TelephoneNumbers`)

| Offset | Field | Meaning |
| --- | --- | --- |
| 0 to 19 | TeleNumber | dialing digits, one per byte; the encoding of pause and special characters is unverified |
| 20 | TeleFlag1 | bit 3 global system events, 4 open and close, 5 zone troubles, 6 bypass, 7 alarms |
| 21 | TeleFlag2 | bit 3 backup of previous number, bits 4 to 7 reporting format (Telephone_Numbers.cs 2477) |
| 22 | TeleAttempts | |
| 23 to 70 | TeleAr1Acct to TeleAr8Acct | six account digits per area |
| 71 to 86 | TeleName | name |
| 87 | TeleNotUsed1 | |

## Globals, 36 bytes, 1 record (`Globals`, Globals_Data.cs)

The flag bytes and their named bits are listed in `specs.py`; the notable
fields are `SysProgramCode` at offset 18 to 23 (the Installer Program Code,
stored like a user code), `SendString` at offset 31 (the serial port transmit
options that the ASCII automation protocol depends on: event log, zone,
output, task, and lighting change broadcasts, and "serial commands require
code"), and `Global1Flags6` at offset 35 whose low bits hold the serial baud
code. On firmware above 4.3 the wire record is 48 bytes: the 36 above followed by
the database columns `S16` to `SDF` and `Country` (Globals_Data.cs 8017-8033,
which reads `Fields[num + 4]` for those, skipping `AntiTakeover`). ElkRP
keeps `AntiTakeover` as a 49th byte of its in-memory array and reads and
writes it with its own commands (`7F 00 00 0C`, `FF 00 00 0C`). The whole
49-byte array is RC4 obfuscated in the database; see `security.md`.

## Lighting, 28 bytes, 256 records (`X10Outputs`)

One flag byte (bit 1 two way, bits 2 to 4 type, bits 5 to 7 format), 15 name
characters, six voice word ids.

## Voice message, 12 bytes (`VoiceMessages`)

Six voice word ids.

## Not yet modelled

Report codes (system, keypad panic, per zone, per user, per area), wireless
zones and RF groups, rules and text packets, constants and variables, sunrise
and sunset tables, email definitions, and the opaque M1XEP configuration
blobs are present in the database schema but have no spec yet. They are the
remaining ElkRP forms; see `docs/backlog.md`.

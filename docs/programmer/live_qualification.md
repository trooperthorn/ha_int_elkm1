# Live qualification

Every exchange with a real panel is recorded here with the frames sent and
received, so that a claim in `protocol.md` can be moved from unverified to
verified with evidence.

## 2026-09-06, attempt on COM3: panel silent

Before any RP login, the panel on `COM3` (FTDI USB serial, VID 0403 PID
6001, the adapter the automation integration qualified on 2026-09-05) was
probed with the ASCII version request `06vn0056` at every rate the panel
supports (115200 down to 300) and then listened to for 35 seconds at 115200
for the unsolicited `XK` broadcast the panel sends every 30 seconds. Nothing
was received at any rate. The port opened and wrote without error, so the
adapter is present and free; the panel was powered off or not connected to
it. No RP login was attempted and no RP access code was entered. Next: power
the panel, confirm the `XK` broadcast appears, then run the plan below.

## First session plan, reads only

No RP session has been run yet. The plan:

1. Connect on the non-secure port or serial, log in with the RP access code.
   Record the full login reply as hex and compare against the layout in
   `protocol.md`.
2. Leave the session idle for 40 seconds and confirm the keepalive keeps it
   open.
3. Read Area 1. Compare the 24 bytes with the ElkRP account's
   `AreaDefinitions` row for the same panel.
4. Read Zone 1 and User 1 the same way.
5. Read Globals and confirm 48 bytes arrive above firmware 4.3.
6. Request the record CRC for Area 1 and compare it with the CRC of the
   bytes read in step 3 computed with `framing.crc16`.
7. Disconnect and confirm the panel's `IE` broadcast appears on the ASCII
   side, which is how the automation integration learns programming ended.

"""Run this yourself - prompts for your passcode once via getpass (hidden input,
never written anywhere). Verifies which of the 8 areas that code is authorized
for, two ways:

1. `ua` (Request User Code Areas) - a read-only info query. You send it the code
   value and the panel replies with a 'valid_areas' bitmask: which areas that
   code can actually control. This changes no panel state.
2. A live `a0` (Disarm) sent to each of the 8 areas in turn with that code. The
   panel is already disarmed everywhere, so this is a no-op state-wise - it just
   confirms, area by area, whether the panel's IC reply reports the code as
   valid (user >= 0) or invalid (user == -1) for that specific area.

Nothing here arms, bypasses, or writes any panel state. Only Disarm (already the
panel's current state) and read-only status requests are sent.

Requires: pip install pyserial
"""
import getpass
import time
import serial

PORT = "COM3"
BAUD = 115200
NUM_AREAS = 8


def checksum(body: str) -> str:
    total = sum(ord(c) for c in body) % 256
    cc = ((total ^ 0xFF) + 1) % 256
    return f"{cc:02X}"


def finalize(body_no_len: str) -> bytes:
    length = len(body_no_len) + 2
    body = f"{length:02X}" + body_no_len
    return (body + checksum(body) + "\r\n").encode("ascii")


def send(ser: serial.Serial, body_no_len: str, timeout: float = 2.0) -> str:
    frame = finalize(body_no_len)
    ser.reset_input_buffer()
    ser.write(frame)
    deadline = time.monotonic() + timeout
    buf = b""
    while time.monotonic() < deadline:
        chunk = ser.read(256)
        if chunk:
            buf += chunk
            if b"\r" in buf:
                break
    return buf.decode("ascii", errors="replace")


def find_frame(reply: str, code2: str) -> str | None:
    for line in reply.split("\r"):
        line = line.strip("\n")  # a bare split on "\r" leaves a leading "\n"
        # on every frame but the first, which shifts these fixed-offset field
        # indices by one character - caught this when a UA frame landed second
        # in the buffer and its bitmask silently failed to decode.
        if len(line) >= 4 and line[2:4] == code2:
            return line
    return None


def main() -> None:
    code = getpass.getpass("Enter the panel's User Passcode (input hidden): ").strip()
    if not code.isdigit() or len(code) > 6:
        raise SystemExit("Code must be numeric, up to 6 digits")
    code_field = code.zfill(6)

    with serial.Serial(PORT, baudrate=BAUD, timeout=2.0) as ser:
        print("\n--- ua: Request User Code Areas (read-only) ---")
        ua_reply = send(ser, f"ua{code_field}00")
        print(f"Raw: {ua_reply!r}")
        ua_frame = find_frame(ua_reply, "UA")
        if ua_frame:
            valid_areas = int(ua_frame[10:12], 16)
            authorized = [a + 1 for a in range(NUM_AREAS) if valid_areas & (1 << a)]
            print(f"valid_areas bitmask: {valid_areas:#010b}")
            print(f"Authorized areas per UA: {authorized if authorized else '(none)'}")
        else:
            print("No UA frame in reply - could not determine authorized areas this way.")

        time.sleep(0.4)

        print("\n--- a0: Disarm sent to each area 1-8 (no-op state-wise, already disarmed) ---")
        per_area_result: dict[int, str] = {}
        for area in range(1, NUM_AREAS + 1):
            reply = send(ser, f"a0{area}{code_field}00")
            ic_frame = find_frame(reply, "IC")
            if ic_frame:
                user = int(ic_frame[16:19]) - 1
                per_area_result[area] = f"ACCEPTED (user {user + 1})" if user >= 0 else "REJECTED"
            else:
                per_area_result[area] = "no IC frame - inspect raw reply"
                print(f"  area {area} raw reply: {reply!r}")
            time.sleep(0.4)

        print("\n--- Summary ---")
        for area, result in per_area_result.items():
            print(f"Area {area}: {result}")


if __name__ == "__main__":
    main()

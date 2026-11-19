"""Run this yourself - prompts for your passcode once via getpass (hidden input,
never written anywhere).

Tests a real arm-then-disarm cycle on AREA 2 specifically, not area 1: area 2 has
no zones assigned to it (confirmed by the earlier 'as'/'zp' live captures - it
reads READY_TO_ARM with nothing to check), so arming it cannot trigger a real
alarm the way arming area 1 could (area 1's zone loops read VIOLATED/OPEN since
nothing is wired to them). This deliberately avoids that risk rather than
bypassing area 1's zones to work around it.

Sequence: arm away (area 2) -> wait 2s -> request status (as) -> disarm (area 2)
-> wait 1s -> request status (as) again to confirm back to fully disarmed.

If anything looks wrong at any point (alarm_state active, unexpected area
affected), stop and tell me - don't keep going on your own judgment call here.
"""
import getpass
import time
import serial

PORT = "COM3"
BAUD = 115200
TEST_AREA = 2  # has no zones assigned; see docstring


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
        line = line.strip("\n")
        if len(line) >= 4 and line[2:4] == code2:
            return line
    return None


def print_area_status(reply: str, label: str) -> None:
    as_frame = find_frame(reply, "AS")
    if not as_frame:
        print(f"[{label}] no AS frame found - raw: {reply!r}")
        return
    armed = as_frame[4:12]
    arm_up = as_frame[12:20]
    alarm = as_frame[20:28]
    print(f"[{label}] area {TEST_AREA} armed_status={armed[TEST_AREA - 1]!r} "
          f"arm_up_state={arm_up[TEST_AREA - 1]!r} alarm_state={alarm[TEST_AREA - 1]!r}")
    print(f"[{label}] full: armed={armed} arm_up={arm_up} alarm={alarm}")


def main() -> None:
    code = getpass.getpass("Enter the panel's User Passcode (input hidden): ").strip()
    if not code.isdigit() or len(code) > 6:
        raise SystemExit("Code must be numeric, up to 6 digits")
    code_field = code.zfill(6)

    with serial.Serial(PORT, baudrate=BAUD, timeout=2.0) as ser:
        print(f"\n--- a1: Arm Away, area {TEST_AREA} ---")
        reply = send(ser, f"a1{TEST_AREA}{code_field}00")
        print(f"Raw: {reply!r}")
        ic = find_frame(reply, "IC")
        if ic:
            user = int(ic[16:19]) - 1
            print(f"IC: user={user} ({'accepted' if user >= 0 else 'REJECTED - stopping'})")
            if user < 0:
                return

        time.sleep(2.0)

        print("\n--- as: status after arm ---")
        status_reply = send(ser, "as00")
        print(f"Raw: {status_reply!r}")
        print_area_status(status_reply, "after arm")

        time.sleep(1.0)

        print(f"\n--- a0: Disarm, area {TEST_AREA} ---")
        reply = send(ser, f"a0{TEST_AREA}{code_field}00")
        print(f"Raw: {reply!r}")

        time.sleep(1.0)

        print("\n--- as: status after disarm ---")
        status_reply = send(ser, "as00")
        print(f"Raw: {status_reply!r}")
        print_area_status(status_reply, "after disarm")


if __name__ == "__main__":
    main()

"""Run this yourself - it prompts for your passcode at runtime (masked, via getpass)
so it is never typed into a script, seen by anyone else, saved to disk, or left in
shell history. Nothing here logs or writes the code anywhere.

What it does: sends a single Disarm (a0) command to area 1 with whatever code you
type in. The panel is already disarmed, so a valid code causes no state change -
this only proves the panel accepts the code instead of returning the same "IC
invalid code" rejection we saw with the wrong one. It intentionally does NOT try
to arm anything: your zone loops currently read VIOLATED (open, since nothing is
wired to them), and force-arming a violated zone can trigger a real alarm the
instant it arms. If you want to test an actual arm/disarm cycle later, do that as
its own deliberate step, not folded into this one.

Usage:
    python elk_valid_code_test.py
    (it will prompt: "Enter the panel's User Passcode: ")

Requires: pip install pyserial
"""
import getpass
import time
import serial

PORT = "COM3"
BAUD = 115200
AREA = 1  # 1-based, area 1


def checksum(body: str) -> str:
    total = sum(ord(c) for c in body) % 256
    cc = ((total ^ 0xFF) + 1) % 256
    return f"{cc:02X}"


def build_disarm(area: int, code: str) -> bytes:
    if not code.isdigit() or len(code) > 6:
        raise ValueError("Code must be numeric, up to 6 digits")
    code_field = code.zfill(6)  # left-padded to 6 digits, per the protocol spec
    data = f"a0{area}{code_field}"
    body_no_len = data + "00"
    length = len(body_no_len) + 2
    body = f"{length:02X}" + body_no_len
    return (body + checksum(body) + "\r\n").encode("ascii")


def main() -> None:
    code = getpass.getpass("Enter the panel's User Passcode (input hidden): ").strip()
    frame = build_disarm(AREA, code)

    with serial.Serial(PORT, baudrate=BAUD, timeout=2.0) as ser:
        ser.reset_input_buffer()
        ser.write(frame)
        print(f"Sent disarm request for area {AREA} ({len(frame)} bytes).")
        deadline = time.monotonic() + 2.0
        buf = b""
        while time.monotonic() < deadline:
            chunk = ser.read(256)
            if chunk:
                buf += chunk
                if b"\r" in buf:
                    break

    reply = buf.decode("ascii", errors="replace")
    print(f"Raw reply: {reply!r}")

    # IC ("Send Valid Or Invalid User Code") is used for BOTH outcomes - the only
    # way to tell them apart is the decoded user field, not whether "IC" appears
    # in the reply at all. A prior version of this script got that wrong.
    ic_frame = next((line for line in reply.split("\r") if line[2:4] == "IC"), None)
    if ic_frame:
        user = int(ic_frame[16:19]) - 1
        if user < 0:
            print(f"\nResult: REJECTED - panel's IC reply reports an invalid code (user={user}).")
        else:
            print(f"\nResult: ACCEPTED - panel's IC reply reports valid user number {user + 1}.")
    elif not reply:
        print("\nResult: no reply received within 2 seconds.")
    else:
        print("\nResult: no IC frame seen - inspect the raw bytes above.")


if __name__ == "__main__":
    main()

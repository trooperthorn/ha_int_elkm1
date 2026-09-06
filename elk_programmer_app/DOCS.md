# Elk Programmer

Installer programming for an Elk-M1 Gold panel from Home Assistant, on
demand. The app packages the `elk-programmer` service and runs it behind
ingress. It is stopped by default and stops itself when idle.

## Options

| Option | Meaning |
| --- | --- |
| `connection` | `serial` for the panel's RS-232 port on this host (the usual case), `network` for an M1XEP. |
| `serial_port` | The serial device, chosen from the host's tty devices. Use the by-id path. |
| `baud` | The panel's Port 0 rate, Global option G34. Factory default 115200. |
| `host`, `port` | Only for `network`: the M1XEP address and its non-secure port. |
| `release_integration` | Disable the `elkm1` integration's entries for the duration of a session and re-enable them afterwards. A serial port is exclusive, so this is required for `serial`; during the session the alarm entities are absent and automation commands fail. |
| `allowed_users` | Home Assistant user ids permitted to open the app. Everyone else receives a refusal on every request, including admins. Find a user id under Settings, People, the user, in the ID field. |
| `idle_minutes` | Minutes without a request before the app stops itself. |
| `read_only` | When true, the app refuses every write to the panel regardless of session state. Leave it true until the first live session has been reviewed. |

Nothing secret is an option. The app passphrase is set from the app's own
page on first use and stored as a hash under the app's data. The panel's RP
access code is entered when a session opens and is never stored.

## Installing

The app is built on the Home Assistant host from its Dockerfile the first
time it is installed; expect a few minutes while the base image and the
service's Python dependencies download. No pre-built image is published yet.

## Using it

1. Start the app from its page. It does not start with Home Assistant.
2. Open it from the sidebar. On first use, set the app passphrase; on later
   uses, enter it.
3. Load or import an account, connect to the panel with the RP access code,
   and use Receive all to read the panel's programming.
4. To change the panel, enable writes (the passphrase again), edit a record,
   and send it. Every send shows the exact frame and asks for confirmation.
5. Disconnect. The app stops itself after the idle period.

Every session, login attempt, receive, and write is recorded in a
tamper-evident audit log under the app's data. With `release_integration`
on, the app disables the `elkm1` integration before it opens the port and
re-enables it when the session ends or the app stops for idleness; if the app
is stopped in between, it re-enables the integration the next time it starts.

## Recovery

If the passphrase is lost, delete `passphrase.json` from the app's data
directory on the host; the next visit asks for a new one. There is no
recovery from inside Home Assistant on purpose.

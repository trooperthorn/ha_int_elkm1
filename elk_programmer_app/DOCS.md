# Elk Programmer

Installer programming for an Elk-M1 Gold panel from Home Assistant, on
demand. The app packages the `elk-programmer` service and runs it behind
ingress. It is stopped by default and stops itself when idle.

## Options

| Option | Meaning |
| --- | --- |
| `host` | The M1XEP address. The panel is reached over the network from this host. |
| `port` | The XEP port for the programming session. Defaults to the non-secure port 2101. |
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
tamper-evident audit log under the app's data. The `elkm1` integration marks
the panel as in remote programming for the duration and rejects automation
commands until the session ends, then resyncs.

## Recovery

If the passphrase is lost, delete `passphrase.json` from the app's data
directory on the host; the next visit asks for a new one. There is no
recovery from inside Home Assistant on purpose.

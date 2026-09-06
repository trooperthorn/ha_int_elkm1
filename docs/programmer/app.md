# Running as a Home Assistant app

This document is the design for packaging the programmer as a Home Assistant
app (formerly add-on) on the host that reaches the panel, and for the
controls that keep a panel programmer from being reachable by anyone who
happens to have a Home Assistant login. The packaging lives in the separate
repository `elk_programmer_app/`; the behaviour lives in this service
under "app mode". Every control below is labelled enforced or advisory and
says which party enforces it.

## Why an app and not part of the integration

The `ha_int_elkm1` integration operates a configured panel: it runs inside
the core process as long as its entry is loaded, its services are callable by
any admin and any automation, and its config entry would be the only place to
keep a credential. A programmer needs the opposite properties: it should not
exist as a process most of the time, it needs a page, it must hold no
credential at rest, and a bug in it must not take the alarm entities with it.
An app is a separate container with its own AppArmor profile that is started
when needed and stopped when done.

## Layers, outside in

| Layer | Control | Enforced by | Status |
| --- | --- | --- | --- |
| 1 | The app is stopped by default (`boot: manual`) and stops itself after an idle period through the Supervisor's `addons/self/stop` endpoint, which needs no API grant | Supervisor | enforced |
| 2 | No `ports` mapping and no `host_network`; the only way in is ingress | Supervisor | enforced |
| 3 | Only the Home Assistant host can reach the M1XEP's ports | the network firewall, outside this design | operator's responsibility |
| 4 | Ingress requires a Home Assistant login; the sidebar entry is admin-only (`panel_admin: true`) | Supervisor and core | enforced for the login; whether a non-admin who knows the ingress URL is refused is unverified, so layer 5 does not rely on it |
| 5 | Allow-list of Home Assistant user ids, checked on every request against the `X-Remote-User-Id` header the Supervisor adds under ingress | this service | enforced |
| 6 | The app passphrase, required to read anything. Argon2-class hash (scrypt from the standard library) stored under `/data`, never in `options.json`, never in a backup of the options | this service | enforced |
| 7 | Step-up for writes: the passphrase again, then the panel's RP access code to open the session. The RP code is used for one login frame and discarded | this service and the panel | enforced |
| 8 | Every write shows the exact frame and requires confirmation; before a write the panel's CRC for the record must equal the CRC of the copy received in this session | this service, using the panel's own CRC command | enforced |
| 9 | Anti-takeover, the installer code, defaulting, flash mode, and firmware commands are not exposed | this service | enforced by omission |
| 10 | Hash-chained audit log under `/data` with the Home Assistant user id from the ingress header, every session event, every frame written | this service | enforced (tamper-evident, not tamper-proof) |
| 11 | The integration records the session: a binary sensor, two events, and a claim service the app calls so the session is attributed to the app and the user | `ha_int_elkm1` | advisory (anyone who can call the service can claim to be the app) |

What none of this defends against: root on the Home Assistant host. Anything
running there can read the container's storage and the passphrase hash. The
passphrase is a shared secret; the audit log ties each use to an HA user id,
which is where per-person attribution comes from.

## The passphrase

- No default. Until a passphrase is set the service answers every request
  except the setup call with 403, and setup itself requires an allow-listed
  user. The setup call is refused once a hash exists.
- Hash: `hashlib.scrypt` with n=2^15, r=8, p=1, a 16-byte random salt, stored
  as JSON in `/data/passphrase.json` with mode 0600.
- Sessions: a random 32-byte token in an `HttpOnly`, `SameSite=Strict`
  cookie, bound to the ingress user id that logged in, expiring after 15
  minutes without a request. A token presented with a different user id is
  refused and logged.
- Step-up: enabling writes re-checks the passphrase and marks the session
  write-capable for 15 minutes. Write endpoints refuse sessions without it.
- Lockout: after five failures the service refuses passphrase checks for 15
  minutes and logs the source user id. Failures are also delayed by one
  second each so a script cannot race the counter.
- Rotation: requires the current passphrase. Recovery: none from inside Home
  Assistant; delete `/data/passphrase.json` from the host console, which
  requires host access and leaves a visible gap in the audit chain.

## The audit log

`/data/audit.jsonl`, one JSON object per line: timestamp, HA user id and
name, event, details, the SHA-256 of the previous line, and the SHA-256 of
this line's content plus the previous hash. The first line hashes over an
empty previous value. A verifier walks the chain and reports the first break.
Events: setup, login, login_failed, lockout, logout, step_up, panel_connect,
panel_disconnect, receive_started, receive_finished, record_read, record_sent
(with the frame in hex), record_verify, idle_stop. The RP access code and
the login frame are never written to the log or the trace.

## Coexistence with the integration

The panel arbitrates: while an RP session is open it answers ASCII polls with
its "remote programming connected" status, and the integration decodes that
into a pause that rejects every command with an explicit error until the
"disconnected" broadcast, then resyncs on the installer-mode-exited
broadcast. That is the backstop.

The explicit hand-off is for the app to call the integration's
`elkm1.programming_session_start` service before login and
`elkm1.programming_session_end` in its finally block, passing its slug, the
HA user id, and the purpose. The integration correlates the claim with the
panel's RP broadcast and exposes:

- `binary_sensor.<panel>_remote_programming`, on between the RP-connected
  reply and the RP-disconnected broadcast, with `last_started`, `last_ended`,
  `session_count`, and `source` (the claimed slug, or `unattributed` when the
  panel reported a session no one claimed).
- Events `elkm1.programming_started` and `elkm1.programming_ended` with the
  same fields plus `attributed`, and the panel's own log entry number for
  events 1363 and 1364 when the transmit-log option is on.
- A Repair issue when a claim has no RP broadcast within its window, or an
  RP session has no claim.

Calling the integration's services from the app needs `homeassistant_api:
true`, the one API grant the app takes. It uses that grant for nothing else;
in particular it does not disable the config entry, because the pause the
panel itself imposes is sufficient and keeps the alarm entities present.

## What the app needs from the Supervisor

`config.yaml`: `boot: manual`, `startup: application`, `ingress: true` on
port 8099, `panel_admin: true`, `homeassistant_api: true`, `init: false`,
a custom `apparmor.txt`, `map: []`, no `ports`, no `host_network`, no
`devices` or `uart` (the panel is reached over the network). Options: `host`,
`port`, `allowed_users` (list of HA user ids), `idle_minutes`, `read_only`.
Nothing secret is an option. With ingress and a custom AppArmor profile the
Supervisor's rating is the maximum; the more important property is that every
grant it omits is one it does not need.

## Unverified

- That the M1XEP accepts the RP protocol on the non-secure port the ASCII
  integration uses. ElkRP's templates default to the secure port with the
  AES-wrapped login this project does not implement. One live test settles it.
- Whether ingress refuses a non-admin user who knows the URL. Layer 5 makes
  this moot for access control; it still matters for the sidebar UX.
- The RP-connected reply timing over the network: whether the integration's
  next poll sees it immediately or after one queued command. Relevant only to
  the window before the integration pauses.

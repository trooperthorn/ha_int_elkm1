# Security

## Trust boundaries

| Boundary | Who is on each side | Control |
| --- | --- | --- |
| Browser to service | the operator's browser and this process on the same machine | the service binds to 127.0.0.1 only; there is no authentication, so anything that can reach localhost can operate the open account and any open panel session. Enforced by the bind address. |
| Service to panel | this process and the Elk-M1 over TCP or RS-232 | the panel authenticates the session with the RP access code; the non-secure network port carries it in clear. Enforced by the panel. |
| Service to ElkRP database | this process and a Jet file | read only connection; the file's password is a shared secret embedded in ElkRP and offers no real protection. Advisory. |
| Account files | this process and the file system | plain JSON; user codes are stored as the panel stores them. Protect the directory with file system permissions. Advisory. |

## Secrets

- The RP access code is accepted per login request, used to build one
  message, and discarded. It is not written to the account file, the trace,
  or the log.
- The database password is accepted per import request and discarded.
- The trace records every frame in both directions. The login frame carries
  the RP access code digits, so the trace of a session that logged in
  contains the code. The trace lives in memory for the session and in the
  GUI's trace pane; it is not written to disk by the service.
- User PINs are panel programming and appear in the user code records, the
  account file, and the wire frames, exactly as in ElkRP.

## ElkRP's own database protection, and what it is worth

ElkRP's account database is guarded three ways, none of which protects
anything from someone who has the database file:

- Jet user-level security: a workgroup file `SOps2.mdw` next to the
  database, user name `ElkRP`, and a password. All three are the same in
  every copy of ElkRP (`Module1.cs 1583`, `2754`) and the password is public.
- RC4 over the user code rows, the globals row (which holds the Installer
  Program Code), and the serial number, MAC address, cloud id, and RP access
  code columns of the account row (`ElkSafe2`, `cr.cs`; `Account_Details.cs
  3710-3764`). The key is eight fixed bytes mixed with the account id and,
  for user rows, the code number (`M1Fns.cs 11731-11760`). Fixed bytes shared
  by every installation are obfuscation, not encryption.
- Report output masks the serial number and RP code with asterisks unless
  the operator has the view permission; the data underneath is the same.

This application reproduces the RC4 so existing databases can be read. It
decrypts user codes and globals into the account, because they are the
panel's programming, and the serial number into the panel identity. It does
not read the RP access code or MAC address columns at all: the RP code is a
credential this application only ever accepts per login.

## Supply chain of the app

The app container is built on the Home Assistant host, so what reaches it is
what can be verified:

- The release workflow builds the programmer wheel from the tagged commit,
  generates an SPDX SBOM for it, records its SHA-256 in `SHA256SUMS`, and
  attests both build provenance and the SBOM with GitHub's attestation
  service. The same is done for the HACS archive of the integration.
- The app Dockerfile downloads the wheel for its own version from that
  release and refuses to install it unless the checksum matches
  `SHA256SUMS`. It never installs from a moving git ref in production;
  the git path exists only so CI can scan a pull request's image.
- Before every merge, CI builds that image, checks the runtime it contains
  (the interpreter version, the package import, no git left behind), and
  fails on HIGH or CRITICAL vulnerabilities in its installed packages.
  `run.sh` is checked with ShellCheck. Bandit runs over the service source
  as well as the integration.

What this does not cover, said plainly: the wheel's Python dependencies are
resolved at image build time on the host from PyPI and the Home Assistant
wheel index at whatever versions satisfy the ranges, so the SBOM describes
the programmer package, not the container that ends up running. Pinning
those dependencies is in the backlog. Verification of the attestations at
build time on the host is also not done; the checksum file is trusted over
TLS from GitHub, which is the same trust the git path had.

## What is not implemented on purpose

- The secure-network login variant appends 16 bytes of AES ciphertext under
  a key embedded in every copy of ElkRP (`M1Fns.cs 12379-12401`). A key that
  every installer's laptop shares is not a secret. On a trusted network
  segment the non-secure port is no worse; on an untrusted one, neither is
  acceptable and a VPN or the serial port is the answer.
- The legacy AES transport (`NetAES.cs`) derives its key from the MAC
  address and passphrase, and the ElkLink and M1Cloud relays authenticate to
  Elk's hosted services with credentials also embedded in ElkRP. None are
  implemented.
- Defaulting the control (`7F 00 AA 55`), entering flash mode, firmware
  programming, and the manufacturing commands are not exposed. Each is
  irreversible or can leave the panel unbootable.
- Changing the RP access code is not exposed until the login path has been
  qualified live; a wrong write here locks the installer out of remote
  programming and ElkRP itself warns of a factory charge to recover.

## Writes

Every write is shown as the exact frame before it is sent and requires a
confirmation. The service refuses to send any table whose wire mapping has
not been traced to the source. The anti-takeover flag is deliberately not
writable from this application: once set it cannot be cleared even by a
factory default, and the only reason to set it is to lock out other
installers.

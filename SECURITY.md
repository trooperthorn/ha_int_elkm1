# Security Policy

## Reporting a vulnerability

Do not open a public issue containing exploit details, credentials, private
addresses, or logs. Use GitHub's private vulnerability-reporting feature for
this repository. If private reporting is unavailable, open a minimal issue
asking the maintainer to establish a private channel; omit technical details.

Include the affected version/commit, prerequisites, impact, a minimal
reproduction, and suggested remediation. Remove PIN codes, user codes,
M1XEP credentials, and private network details.

## Response targets

These are project targets, not an SLA: acknowledge critical/high reports in
three business days, establish severity and containment in seven, and publish
a coordinated fix as soon as safely validated. Lower-severity issues are
prioritized by exploitability and impact.

## Supported version

Only the latest published release and the default branch receive security
fixes. Operators should update Home Assistant and this integration promptly
and retain a tested rollback/backup.

## Security boundaries

This integration talks to an Elk-M1 panel over RS-232 or over the M1XEP
network module. The RS-232 ASCII protocol has no authentication, and the
M1XEP's non-secure port has none either; the secure port authenticates with a
username and password sent over TLS but the panel accepts the PIN codes that
Home Assistant service calls carry as plain integers. Anyone who can reach
the serial port or the M1XEP therefore has the same authority this
integration has. The integration does not harden the panel, the network
segment, or the Home Assistant host; it validates service input and keeps
credentials in the config entry, which Home Assistant stores unencrypted on
disk.

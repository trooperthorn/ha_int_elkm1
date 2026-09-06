# Changelog

## Unreleased

- Serial connection to the panel from the Home Assistant host (`uart`, a
  serial device option, baud), and release of the `elkm1` integration's
  entries around a session because a serial port is exclusive. Fixes the
  local build on the base image's Python 3.12.

## 2026.09.06.1

- First skeleton: ingress-only packaging of the elk-programmer service with
  a user allow-list, app passphrase, audit log, and idle self-stop. The
  container image is not yet published and the panel protocol is not yet
  live-qualified.

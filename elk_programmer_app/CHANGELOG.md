# Changelog

## Unreleased

- Every panel session is announced to the `elkm1` integration through its
  `programming_session_start` and `programming_session_end` services, so
  the session is attributed to the app and the Home Assistant user rather
  than reported as unknown.
- The Dockerfile installs the programmer wheel published by the release of
  the same version and verifies its SHA-256 against the release's
  `SHA256SUMS`; releases carry SPDX SBOMs and provenance attestations, and CI
  builds and scans the image before every merge.
- Serial connection to the panel from the Home Assistant host (`uart`, a
  serial device option, baud), and release of the `elkm1` integration's
  entries around a session because a serial port is exclusive. Fixes the
  local build on the base image's Python 3.12.

## 2026.09.06.1

- First skeleton: ingress-only packaging of the elk-programmer service with
  a user allow-list, app passphrase, audit log, and idle self-stop. The
  container image is not yet published and the panel protocol is not yet
  live-qualified.

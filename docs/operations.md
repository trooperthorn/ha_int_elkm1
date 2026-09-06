# Operations

Configuration knobs, the test gate, and the release path. Protocol and device
facts live in `protocol.md`; design rationale lives in `design.md`.

## Test gate

The gate is the same on a workstation and in CI: `ruff check .`, `mypy
--config-file mypy.ini custom_components/elkm1`, `pytest -ra --strict-markers
tests/`, then `python scripts/build_release_artifacts.py --validate-only`.
Pins live in `requirements-dev.txt` and `requirements-core.txt`. The Home
Assistant test harness (`pytest-homeassistant-custom-component`) pins the
beta core it was cut from, and pip refuses to resolve a different core in the
same install, so the stable `homeassistant` pin lives in its own file and is
installed second. The CI job asserts the installed core version so a harness
bump that silently moves the core is caught. The harness imports
`fcntl`, so on Windows the suite runs under WSL.

## Live hardware debug check

`scripts/live_debug_check.py` runs the real integration - config entry setup,
the coordinator, entity-registry forwarding, clean unload - against a real
panel, for debugging a connectivity problem or as a release-qualification
step. It is not part of the CI gate (it touches a real serial connection)
and is read-only by design: no arm/disarm/output/bypass/write
command is ever sent. Unlike the full pytest suite, only the harness's
`common.py` helpers are needed, not `plugins.py` (which imports `fcntl`), so
this one script runs natively on Windows against a COM port with no WSL
detour: `python scripts/live_debug_check.py --port COM3 -v`. See
`docs/live_qualification.md`'s sixth 2026-09-05 entry for what it verified
and why the harness needs a couple of workarounds (a domain collision with a
built-in core `elkm1` integration; a `ContextVar`-only deprecation notice
that only misfires because this script's call stack isn't a real
integration-loader frame).

## Release path

A merge to `main` is the only release path. Nobody edits the manifest
version or pushes a tag by hand.

1. `Release` runs on every push to `main`. It calls the Test and Validate
   workflows, then reads the version from `custom_components/elkm1/manifest.json`
   through `.release.json`. If a published release for that version already
   exists it stops. Otherwise it creates the `v<version>` tag on the exact
   commit, drafts a release with generated notes, and publishes it. HACS
   installs the tagged tree, so no archive or checksum is attached.
2. `Prepare release` runs after every successful `Release` on `main`. When the
   manifest version equals the latest published release and
   `custom_components/elkm1` changed since that tag, it runs
   `scripts/set_version.py --next-from-tags`, pushes the bump to
   `automation/calver-release` with a GitHub App token, opens a PR, and arms
   squash auto-merge. The merge triggers `Release` again, which publishes the
   new version. Docs, tests, and workflow changes do not bump the version.
3. Without the GitHub App credentials the second step fails at its credential
   check and nothing else happens. The repository still releases: run
   `python scripts/set_version.py --next-from-tags` on a branch, open the PR,
   and the merge publishes.

`.release.json` is the single statement of what ships: the tag prefix (`v`,
matching every existing tag), the time zone the CalVer date is taken in, the
release-bearing path, and the version field. `scripts/set_version.py` is the
only writer of that field; `scripts/release_config.py` and
`scripts/build_release_artifacts.py --validate-only` are the independent
reader the workflows use, so a writer defect cannot validate itself.

Versions are `YYYY.MM.DD.N` in `America/Chicago`. `set_version.py` counts
existing tags for the day to pick `N`.

### GitHub App for zero-touch version PRs

`Prepare release` needs a GitHub App with repository permissions Contents:
Read and write and Pull requests: Read and write, installed on this
repository, plus the repository variable `RELEASE_AUTOMATION_CLIENT_ID` and
the Actions secret `RELEASE_AUTOMATION_PRIVATE_KEY`. The same App can be
installed on every trooperthorn Home Assistant repository; each repository
holds its own copy of the variable and secret. The App token is created only
after the workflow has proved a bump is needed, expires on its own, and is
scoped to this repository. The workflow's own `GITHUB_TOKEN` stays read-only.

### Branch and protection settings

`main` is the only long-lived branch. Work happens on short-lived branches
that end in a squash-merged PR and are deleted on merge. Branch protection
requires the job display names `pytest (Python 3.14)`, `HACS validation`,
`hassfest (manifest sanity)`, `CodeQL (python)`, and `Python static security
checks`, with strict up-to-date checks, enforced for administrators, no force
pushes, no deletions, and no required approvals, because a single maintainer
cannot approve their own PR and the automation must not need a bypass.

## Release artifacts

A merge to main publishes one release carrying both products: `elkm1.zip`,
the deterministic HACS archive of the integration (HACS installs it because
`hacs.json` sets `zip_release`), and the programmer wheel the app installs by
version. Each has an SPDX SBOM, a line in `SHA256SUMS`, and provenance and
SBOM attestations. The release workflow's summary prints the verification
commands; the short form is `gh attestation verify <asset> -R trooperthorn/ha_int_elkm1`.
The app's Dockerfile checks the wheel against `SHA256SUMS` before installing it.

## Runtime knobs

The options flow allows a poll interval up to 300 seconds. After connecting, the
integration waits five seconds and then logs which Global Programming broadcast settings
it has confirmed active; an "unconfirmed" setting may only mean that nothing of that
type has changed yet, so check the panel before assuming it is off.

Diagnostics exports redact the pin and serial port (`diagnostics.py`'s `TO_REDACT`).

## Line endings

`.gitattributes` pins every text file to LF. Windows checkouts with
`core.autocrlf` used to produce CRLF working copies that broke tools reading
the tree from WSL; the rule now travels with the clone.

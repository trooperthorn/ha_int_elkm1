# Operations

Configuration knobs, the test gate, and the release path. Protocol and device
facts live in `protocol.md`; design rationale lives in `design.md`.

## Test gate

The gate is the same on a workstation and in CI: `ruff check .`, `mypy
--config-file mypy.ini custom_components/elkm1`, `pytest -ra --strict-markers
tests/`, then `python scripts/build_release_artifacts.py --validate-only`.
Pins live in `requirements-dev.txt`: the Home Assistant test harness
(`pytest-homeassistant-custom-component`) pins the beta core it was cut from,
and the explicit `homeassistant` line re-resolves to the stable release the
integration targets. The CI job asserts the installed core version so a
harness bump that silently moves the core is caught. The harness imports
`fcntl`, so on Windows the suite runs under WSL.

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

## Runtime knobs

The options flow allows a poll interval up to 300 seconds. The network heartbeat window
defaults to 120 seconds and is scaled to the poll interval plus 30 seconds so a long poll
interval does not cause spurious reconnects (`protocol.md` has the reasoning). After
connecting, the integration waits five seconds and then logs which Global Programming
broadcast settings it has confirmed active; an "unconfirmed" setting may only mean that
nothing of that type has changed yet, so check the panel before assuming it is off.

Diagnostics exports redact credentials (password, username, pin, code, userid) and network
locators (host, serial port, MAC address).

## Line endings

`.gitattributes` pins every text file to LF. Windows checkouts with
`core.autocrlf` used to produce CRLF working copies that broke tools reading
the tree from WSL; the rule now travels with the clone.

# Backlog

Open items moved out of code, dated when they were recorded.

- 2026-09-03, `entity.py`: every entity shares one panel-wide device. Split into per-area
  and per-keypad devices once those become first-class (a keypad platform, area-aware
  naming).
- 2026-09-03, `number.py`: unnamed counter and custom-value slots are not created; add an
  options-flow opt-in for installs that want them.
- 2026-09-03, `models.py`: `ELKM1Data` is a migration alias of `ElkRuntimeData`; remove it
  once nothing imports it (`diagnostics.py` still does).
- 2026-09-03, `helpers/panel_settings.py`: a panel whose broadcast bits look disabled is
  only logged; raise a Repairs issue instead (`quality_scale.yaml`, `repair-issues`).
- 2026-09-03, release automation: install the release GitHub App on this repository and
  set `RELEASE_AUTOMATION_CLIENT_ID` and `RELEASE_AUTOMATION_PRIVATE_KEY`; until then
  version bumps are manual (see `operations.md`).

# Backlog

Open items moved out of code, dated when they were recorded.

- 2026-09-03, `entity.py`: every entity shares one panel-wide device. Split into per-area
  and per-keypad devices once those become first-class (a keypad platform, area-aware
  naming).
- 2026-09-03, `number.py`: unnamed counter and custom-value slots are not created; add an
  options-flow opt-in for installs that want them.
- 2026-09-03, `helpers/panel_settings.py`: a panel whose broadcast bits look disabled is
  only logged; raise a Repairs issue instead (`quality_scale.yaml`, `repair-issues`).
- 2026-09-05, `coordinator.py`'s `_handle_voice_message` (registered via
  `elk.panel.add_callback`) cannot fire with real word data and should not be trusted as a
  working feature. Traced through `helpers/elk/elements.py`'s `Element.add_callback`: it always
  calls `observer(self, self._changeset)` - two positional args - so `_handle_voice_message`
  takes `args[-1]`, which is the changeset *dict*, fails its own
  `isinstance(words, (list, tuple))` check, and returns immediately every time. Separately,
  the RS-232 protocol spec has no message at all for the panel to report which words it
  spoke or is speaking (`sw`/`sp` are outbound-only, 3rd-party-to-panel); the feature's
  premise does not exist in the protocol either way. Not documented in the README or
  services, and has no test coverage. Needs a decision: remove the dead handler/event, or
  determine whether some other real trigger was intended and wire it up properly.
- 2026-09-05, `helpers/elk/connection.py`'s `MESSAGE_RESPONSE_TIME` lowered 5.0s -> 1.5s
  after a live-hardware incident (`docs/decisions.md`, `docs/live_qualification.md`'s
  seventh entry) - not yet re-verified against real hardware. Re-run
  `scripts/live_full_verification.py`'s `set_panel_time` and zone-bypass steps next time
  the panel is accessible.
Resolved:

- 2026-09-05, `vocabulary.py`'s `ELK_VOICE_VOCABULARY` rebuilt from Elk's own `WordLists`
  reference database (extracted from ElkRP), not the installation manual - superseding the
  manual-vs-earlier-table conflict this item originally tracked. See `docs/decisions.md`.
  Still nice-to-have but no longer blocking: an actual `sw`/`sp` playback audition against
  the real panel, since this is now the manufacturer's own data rather than a
  possibly-stale manual.
- 2026-09-05, `models.py`'s `ELKM1Data` migration alias removed; `diagnostics.py` now
  imports `ElkRuntimeData` directly, the only remaining caller.
- 2026-09-04 (see `docs/decisions.md`), release GitHub App installed on this repository;
  version bumps are zero-touch, not manual.

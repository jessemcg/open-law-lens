# Shared Agent Model validation — 2026-10-18

## Scope

One OpenLawLens-owned model/provider/thinking triple now governs new Law,
Research Cache, Prior Briefs, Case Question and Subsequent Treatment sessions.
Workflow instructions, corpus, metrics identity and existing follow-ups remain
independent. Local Search Briefs remains non-agentic. No public CLI, wrapper,
dependency, launcher, Pi registry, prompt or tool-policy changes.

Loading is read-only. A valid singular `agent_runtime_profile` wins; explicit
null or malformed singular data inherits defaults without consulting legacy
profiles. Only an absent singular key uses valid saved Law. Explicit Settings
Save writes the singular key (including null), preserves opaque legacy profile
JSON/version presence and values, retired prompts and unrelated JSON, and retains
private atomic replacement. No real settings were read for model selection or
rewritten/migrated, and no Pi preferences were changed.

## Isolation and checks

Local Home computer only (`hostname`: `home`). Tracked-source-only disposable
copy: `/tmp/oll-shared-agent-je5ci0/source`; separate environment selected by the
absolute UvEnvironments helper with paired `--project` and `--environment`
overrides. Optional sibling PiRunMetrics copy contains tracked code only, no
archives. Tests run with allowlisted environment, synthetic HOME/XDG/Pi/config/
library/session/metrics/current-case paths; no credentials, private runtime files,
paid inference or other-computer access. Wrapper tests use fake Pi executables.

- Initial isolated suite: 1,202 tests PASS after correcting two harness-only
  overrides (an absent forced Pi settings path and cache-default mismatch).
- Final full suite with isolated tracked PiRunMetrics sibling: **1,204 run,
  1,204 PASS, zero skips** (`suite-final.log`).
- Final full suite without that optional sibling: **1,204 run, 1,202 PASS,
  2 optional-metrics skips** (`suite-no-sibling-final.log`).
- Final actual GTK `--auto`: PASS (`preview-auto-final.log`). One transient GDK
  Vulkan swapchain resize warning did not prevent assertions or clean exit.
- Package/test compilation (`python -m compileall -q open_law_lens tests`),
  unchanged wrapper `bash -n`, and `git diff --check`: PASS.
- All 14 changed implementation/test/current-documentation paths byte-match the
  final tested disposable source. This validation record is separate prose.
- Configuration matrix covers conflicting legacy selections, singular precedence,
  explicit defaults/malformed values, missing/invalid Law, read-only loads,
  private saves and opaque compatibility presence/value preservation.
- Final VTE spawn capture exercises all five workflows with legacy Law fallback
  and defaults under conflicting parent environment triples. Both builder and
  outer environment merge remove stale provider/model/thinking values.
- Standalone authorization tests preserve unavailable-selection failure and reject
  provider/effort/default selection changes during authorization. The selection
  is captured before asynchronous catalog checking starts.
- Fake wrapper tests verify the shared explicit triple for all five workflows,
  distinct fixed skills, confinement and existing metrics/session transport.
  Existing Local Search Briefs and follow-up tests remain part of the full suite.
- `tests/preview_settings.py --auto` exercises the actual SettingsWindow with
  synthetic catalog and files: four shared-list categories, one pair, Law fallback,
  loading/failure Save, unsaved refresh, unavailable retention/recovery, effort
  adjustment/off behavior, default inheritance, save/reopen, close-without-save,
  stale callback rejection, other controls and session-only fact-pattern handling.

## Native desktop validation and limitations

Only owned synthetic preview processes/windows were opened or manipulated.
Computer Use doctor reported no blockers before interaction. Desktop observation
caught that plain Box parenting does not activate ComboRow dropdowns; both rows
now share an unheaded ListBox inside the Agent Model category, retaining one
outer boxed PreferencesGroup and one app scroller. Automated preview explicitly
asserts ListBox parenting to prevent recurrence.

Native Wayland preview PID **453446**, Settings window **1466228349**, used only
synthetic data. Screenshots confirmed the four categories and one compact pair
at **900×760** and **620×760** logical window sizes. Pointer interaction opened
the real model dropdown, showed its wrapping factory, selected the long synthetic
model, refreshed while retaining that unsaved selection, then saved through the
header button. Visible feedback was “Settings saved. Agent model changes apply
to new sessions.” Independent synthetic-file readback confirmed model-2/high,
unchanged legacy Law model-0, and mode 0600. All owned interactive preview
processes were closed. Native acceptance preceded import/format-only cleanup;
the final byte-matched suite/GTK auto run includes that cleanup.

Earlier XWayland attempts had unreliable cropped screenshot geometry and are
not relied on for final pointer acceptance. Native window-only screenshots crop
parts of popovers extending beyond the parent; full-popup behavior on other
physical monitor/scaling layouts was not certified. `xvfb-run` is unavailable
locally, so no Xvfb acceptance or optional `--matrix` snapshot run is claimed;
final suites and auto preview used the local desktop with isolated application
state. Save/reopen, failure/recovery, defaults and stale callback matrices were
verified by the actual GTK auto harness rather than manually repeating every
case with pointer input.

No maintained application restart, real model discovery/inference, real document
processing, private Settings Save, sibling edits, commit or push was performed.
Restart Open Law Lens when convenient to see the simplified UI. Its saved Law
pair supplies the starting shared selection until explicitly changed and saved.

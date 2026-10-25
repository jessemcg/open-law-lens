# Quiet startup and task-time guidance — 2026-10-25

Implemented and validated locally on **Home**. This supersedes the historical
Setup-window acceptance in portability-validation.md. Local source changes are
not publication; future one-line installs receive them only after they are
published to public `main`. Existing installs do not automatically update, and
valid saved font choices are not reset.

## Behavior

- Startup creates/presents/reuses the main window, never a diagnostics window or
  first-run suppression marker. Removed the diagnostics action, menu entry,
  Python GUI module and its GUI-only tests. Missing VTE has a quiet placeholder,
  not unsolicited installation advice. Explicit CLI `doctor` and installer
  progress/errors/completion/optional Pi flows remain.
- `task_prerequisites.py` owns stable reason codes and short messages. Research
  token checks precede executable, terminal/launcher and offline model checks.
  Catalog/default discovery remains in `pi_runtime.py`, with typed executable
  absence/start failures and invalid-response rejection. No HTTP authorization
  verification, paid probe, automatic provider selection or preference writes.
- All five new Agent workflows use the common gate in both storage modes, before
  source validation, export, workspaces or prompts. Cache/Brief questions do not
  require a CourtListener token. Blank/local-search requests do not query Pi.
- Workers and GTK preparation callbacks retain a request generation, effective
  app profile, settings/token snapshot and session-only fact-pattern override.
  New submissions, closure and Settings Save invalidate pending work; changed
  settings detected at publication ask for resubmission. A final guard consumes
  each launch before stopping/clearing an existing session. Live follow-ups keep
  their existing session semantics. No second catalog query after preparation.
- Anonymous CourtListener authentication failures have a distinct typed error;
  invalid credentials and network errors are not relabeled as missing setup.
  Citation lookup still proceeds through its existing browser fallback.
- Missing/invalid Display preferences now use Linux Libertine O / 14 pt. Existing
  supported values, aliases, limits, font-menu order and fallback CSS remain.
  Loading stays read-only; no font distribution or settings migration changes.

## Isolation

Used a tracked/new-source-only disposable OpenLawLens copy and separately
provisioned disposable environment, selected by absolute UvEnvironments helper
`--project` / `--environment` overrides. Used an isolated tracked-source
PiRunMetrics sibling for maintained integration tests. No production Python
environment, settings, credentials, libraries, caches or sessions were copied.

Execution used an allowlisted environment with temporary HOME/XDG paths and no
inherited provider/token credentials. Native previews used a distinct
`NON_UNIQUE` synthetic GTK application identity and their own temporary state;
model catalogs and CourtListener boundaries were synthetic. The installed Pi SDK
was used read-only for offline synthetic-provider/session-transport tests, not
for real inference. Private test writes used umask 077. A first no-display test
attempt could not run GTK; validation was rerun with local Wayland/display access.

## Results

| Check | Result |
| --- | --- |
| Full `unittest discover -s tests` | 1,249 tests; OK, six inapplicable cross-owner model-contract tests skipped |
| Focused config / app handlers / Pi runtime / portability / shared model / task prerequisites / CLI-client patterns | 381 tests; OK |
| Package `py_compile` | PASS in disposable source |
| Implementation `git diff --check` | PASS |
| Explicit `open-law-lens doctor --json` | Exit 0, parseable redacted capability report in synthetic state |
| `tests/preview_portability.py` | PASS native GTK assertions: quiet/repeated startup, no diagnostics action/window, token/Pi/VTE/empty-model messages, preserved question/answer buffer, token-free reading and local search, synthetic Settings Save/reopen, Libertine O/14 defaults and saved Noto Serif/11 |
| `tests/preview_settings.py --auto` | PASS native controls: default Display, boxed expandable categories, explicit Save, inherited effort, refresh/failure/unavailable retention, save/reopen and unsaved-close guards |

Linux Computer Use first observed the scoped disposable app, then checked desktop
readiness before interaction. Exact-window AT-SPI menu activation and screenshot
showed the concise model message, preserved question and five ordinary menu
entries, with no diagnostics item. A later final-code observation confirmed the
message, question, reader text and action list by exact disposable PID; window
introspection had become unavailable then, so no additional targeted input or
system setup was attempted. Preview processes and disposable resources were
cleaned after validation.

Native preview logs included an X11 authorization warning while GTK/Wayland
assertions still passed. No new clean-distro installation, browser-recovery,
paid-model or other-computer acceptance is claimed. Dependency declarations,
lockfile, installers, Desktop_Files and XREMAP were not changed. Production private
runtime state was not used for acceptance or rewritten as a migration/repair.

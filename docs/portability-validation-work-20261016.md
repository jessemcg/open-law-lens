# Portability validation — 2026-10-16

## Scope and isolation

Implemented in OpenLawLens only. Existing maintained CLI/desktop/XREMAP command
routes were inspected and retained; Desktop_Files and XREMAP have independent
unrelated modifications and were not edited. Focus, RecordPrep and UvEnvironments
source were not changed. No production environment synchronization, private
config/library/archive migration, app restart, paid model/research run, browser
recovery or other-computer access occurred.

Current computer: Work. Ubuntu 26.04.1 LTS, GNOME Wayland. Installed native API
versions: GTK 4.22.4, Libadwaita 1.9.1. Test environment: managed Python 3.13,
locked dependencies through paired absolute UvEnvironments project/environment
overrides. Native dependencies/build cache already existed here; no clean-distro
or dnf acceptance claim is made.

The disposable source exported Git-tracked files plus intentional new source
files; no `.venv`, private `config.json`, real caches, libraries, briefs or
sessions were copied. A separate tracked-source PiRunMetrics fixture supplied
maintained offline observer acceptance. The standalone acceptance also ran with
that sibling absent. Routine model execution used the existing synthetic Pi/SDK
fixtures, never a live provider.

## Automated acceptance

- Full unittest discovery: **1,144 tests PASS**, including existing citation,
  extraction, browser-verification, follow-up, rendering, opaque settings,
  completion and confinement coverage; offline observer SDK acceptance included.
  The full suite also PASS with both sibling repositories absent: 1,144 run,
  1,142 passed, two explicitly optional observer integration tests skipped.
- New portability coverage: XDG defaults and no-write resolution; read-only,
  credential-redacted default doctor; missing optional capabilities preserving
  core readiness; unconfigured Current Case; private Settings round trips;
  source-independent command execution from paths containing spaces; all five
  public workflow launches without uv/browser packages or personal defaults;
  no silent provider substitution; private runtime symlink rejection; no tracked
  Pi defaults in standalone RPC discovery; missing-environment launch failure;
  saved answers surviving public cache clear.
- Bash syntax checks, 134 Python sources compiled without bytecode writes,
  instantiated desktop template validation, and whitespace diff check.
- Source file inventory (names, sizes, mtimes) was unchanged across the actual
  synthetic full-window/Setup/save-reopen run.
- Standalone locked-runtime receipt recorded in the **disposable environment**;
  standalone launcher doctor JSON exited 0. Nothing was provisioned at launch.
- Public launcher `app` remained running until the bounded five-second test
  timeout on a separate test D-Bus session with independent HOME/XDG paths, no
  sibling checkout or model credentials. SQLite state appeared only under the
  synthetic XDG data directory, with graphics-driver caches in synthetic XDG
  cache. No application traceback/critical appeared. Isolated D-Bus portal
  activation emitted expected session/Wayland integration warnings; this is a
  startup smoke check, not full desktop-portal acceptance.

## Native GUI acceptance and limitations

`tests/preview_portability.py` constructs the actual full window and Setup view
under a unique application ID, with synthetic XDG roots, empty model catalog and
VTE deliberately unavailable in the GUI. It verifies reader startup, Setup core
readiness and missing-Agent explanation, unconfigured Current Case text, explicit
Settings save to mode 0600, and Settings reopen. PASS.

`tests/preview_settings.py --auto` also PASS: existing shared list/independent
categories, all five model overrides, failure retention, opaque retired values,
source-folder choose/reset, explicit save/reopen and session-only fact overrides.

Native desktop observation read the actual Setup accessibility text and its
buttons, and the parent window's optional-integration explanation. The screenshot
was partial because the test window opened partly off-screen. Exact window
control became unavailable when attempting to reposition it (GNOME targeting
backend unavailable/Introspect denied); no permission/setup changes were made.
There is no full-window visual acceptance or live browser-recovery claim. The
synthetic window/process was closed without touching user windows/documents.

## Remaining publication gates

See [portability.md](portability.md): owner-approved license; a real installer
with confirmation/ownership/upgrade/uninstall protections; known revision
metadata for non-Git source archives; clean native provisioning on explicitly
named supported apt/dnf releases; any broader desktop/browser claims. None is
silently treated as passed by this host's existing native dependency cache.

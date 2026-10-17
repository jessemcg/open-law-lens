# Public source installer validation — 2026-10-17

**Initial published installer baseline.** The subsequent standalone native recovery
runtime, removal of general web search and authorized Home native provisioning
are documented in [the revision's validation and limits](dependency-runtime-validation.md).
Guest runs and package-offer checks below predate that revision.

## Publication and boundaries

Implemented and validated locally on Home (Ubuntu 26.04.1, x86_64, GNOME Wayland).
The owner subsequently authorized separate repository commits and publication.
The README URL requires these source files on `jessemcg/open-law-lens` `main`;
local tests do not establish a successful real public installation. Fresh installs
follow `origin/main`, not an obsolete release manifest. Publication does not imply
maintained deployment or expand the acceptance claims below.

OpenLawLens owns its standalone installer, maintenance engine, runtime fixes,
documentation and GPL v3 license. Desktop_Files adds only public canonical
Open Law Lens templates/exporter/tests. Its pre-existing unrelated changes were
preserved. No Focus, RecordPrep, UvEnvironments, XREMAP, maintained desktop launcher,
shared Pi settings, private application data or credentials were changed. No
`updatedesktopfiles`, real-app restart, model call, login, browser challenge,
host package install, remote-computer control or other-computer operation was performed.

## Isolated automated checks

Tests run from a tracked/intentionally-new-source-only `/tmp` checkout with a
paired `/tmp` managed-Python 3.13 environment, selected through the absolute
UvEnvironments helper. No production environment was synchronized. Public tests
work without any sibling repositories; separate maintained observer tests use a
tracked-source-only PiRunMetrics fixture. All installer HOME/XDG/Pi/source/runtime
resources are disposable. No private runtime configuration was copied.

- `tests/test_source_installer.py`: supported/rejected platforms and package plans,
  Fedora Cairo/ffi prerequisites, apt/dnf removal/availability guards, Enter native
  approval, installer-only storage roots, unsafe roots/symlinks/hardlinks,
  malformed/private receipts, locks, interrupted atomic publication, source/lock
  binding, explicit locked provisioning, repeated sync ownership, real local Git
  clone/failure/resume/repair, maintained-resource collision refusal, source-edit
  preservation, normal uninstall/purge and durable data/session/credential safety.
  Actual desktop-file validation and GIO Exec parsing exercise paths containing
  spaces, apostrophes, dollar signs, backticks and percent signs.
- `tests/test_installer_terminal.py`: short command/template/README agreement,
  curl/wget download-first failure/child status/argument/cleanup behavior, actual
  piped-bootstrap controlling-terminal handoff, failed partial downloads, real
  PTY Enter/skip/EOF/Ctrl+C, plain/styled/ASCII output and stage-based progress.
  A full synthetic terminal lifecycle covers application success before all Pi
  and package offers, user-scope neutral-cwd package argv, existing/custom package
  retention, package/discovery/network/cancellation failure independence.
- `tests/test_pi_install_layouts.py` and the existing wrapper/runtime/Computer Use/
  diagnostics suites: effective Pi agent-directory discovery, official shell
  launch without Node-as-script, official XDG/HOME current Node, legacy symlinked
  JavaScript plus bundled Node, explicit overrides, RPC isolation, and all five
  workflow tool restrictions. The old shell-as-JavaScript fixture was corrected.
- Desktop_Files exporter tests: deterministic export, check/drift failure and
  exclusion from maintained deployment enumeration. Public desktop resource is
  exported to the existing `scripts/open-law-lens.desktop.in`; no competing copy.
- Full suite with the isolated optional observer fixture: **1,194 tests PASS**.
  Without any siblings: **1,194 run, 1,192 PASS, 2 optional observer skips**.
  Desktop_Files: **2 focused exporter tests PASS**. **142 Python files** compile
  without bytecode; shell syntax, README/docs local links, canonical export checks,
  Focus GPL text and whitespace checks also pass. The README is **93 lines**;
  build metadata and `uv.lock` are unchanged. RecordPrep has its own prefatory
  GPL-3.0-or-later declaration/formatting; this LICENSE uses Focus's text with
  only the extra trailing blank line removed.

The real GIO launch test caught a percent-in-executable-path problem that
`desktop-file-validate` alone did not catch. The canonical desktop entry now uses
`/usr/bin/env --` to invoke the quoted standalone command plus `app`; percent
field-code expansion occurs in argument position. The metacharacter-path fixture
then launched correctly with exactly the intended argv.

## Native build smoke: local disposable guests

Local QEMU/KVM guests used official Ubuntu 24.04 and Fedora 44 cloud images,
verified against their official HTTPS SHA256 checksum lists:

| Image | SHA256 |
| --- | --- |
| `noble-server-cloudimg-amd64.img` | `6a81c37564db9b1ee84e141922625e1d7c5b389b99bb3c572e0243607d5bb4d2` |
| `Fedora-Cloud-Base-Generic-44-1.7.x86_64.qcow2` | `28680fe5b371a5a82ebf43a31926e086a168e59949d03969c5093e7071f90b7f` |

Checksums were compared; independent PGP signature-chain verification was not
performed. Guests used local serial consoles/cloud-init seed media only, no SSH,
shared host folders, host credentials, or persistent VM deployment. Guest-only
root package provisioning used the installer's package sets. Code/builds ran as
ordinary guest users. Fresh private uv 0.11.8 provisioned managed Python 3.13.13
and the **unchanged Open Law Lens `uv.lock`**, with `--locked --no-cache`, no host
wheel-cache reuse or distro-Python GI substitution. Both built pycairo/PyGObject,
imported trafilatura, loaded GTK/Adwaita/VTE, passed standalone `--record/--check`,
required API assertions, and CLI `--help`. Both emitted `OLL_LOCKED_BUILD_PASS`
and `OLL_NATIVE_SMOKE_EXIT=0`.

| Guest | Native versions observed | Result |
| --- | --- | --- |
| Ubuntu 24.04 | GLib 2.80, GTK 4.14, Adwaita 1.5, VTE 3.91 typelib | PASS |
| Fedora 44 | GLib 2.88, GTK 4.22, Adwaita 1.9, VTE 3.91 typelib | PASS |

A second ordinary guest user exercised the **real maintenance engine**, local
synthetic Git `origin/main`, actual private uv/Python/dependency provisioning,
real desktop-file/icon integration, installed-launcher final checks, completed
receipt before optional Pi, Pi `skip`, parseable standalone `doctor --json`, and
actual normal uninstall preserving source and durable maintenance. Both guests
emitted `OLL_REAL_INSTALL_PASS`, `OLL_REAL_UNINSTALL_PASS`,
`OLL_FULL_LIFECYCLE_PASS`, and `OLL_FULL_EXIT=0`.

The first guest lifecycle fixture used the wrong diagnostic JSON key; corrected
from `storage_mode` to the real `storage` field. Fedora also exposed its `pandoc`
virtual-provider naming: the installed RPM is `pandoc-cli`; the installer now
requests that concrete package to avoid repeated false-missing transactions.
A waiting synthetic Fedora fixture was terminated before the corrected rerun.
Fedora cloud-init logged a BrokenPipe during immediate guest poweroff **after**
the successful acceptance markers; that is not an application/build failure.
Guest disks and synthetic state are disposable, not an installed host app.

These are native-build and serial lifecycle checks, **not full graphical distro
certification**. Ubuntu 26.04/Fedora 43 clean guests, aarch64, compatible derivatives,
real GNOME applications-menu activation and browser permissions are not certified
by these x86_64 guest checks. Real public GitHub downloading of unpublished files,
real Pi/package installation and paid-provider readiness were not exercised.

## Host synthetic desktop and terminal

`tests/preview_source_install.py` uses the actual maintenance engine with synthetic
native/runtime/optional installers, local fixture Git and a temporary HOME. Full
PTY interaction verifies the eight stages, normal approvals and Pi/package order.
An independently identified Ghostty window was also started and observed through
AT-SPI at the initial approval; only that synthetic process was canceled/cleaned.

`tests/preview_portability.py` passed actual core reader startup without Pi/VTE,
first-run Setup, unconfigured optional Current Case and explicit synthetic
Settings save/reopen with mode 0600. Computer Use's PID-scoped AT-SPI observation
confirmed the separately identified reader/Setup windows, capability report and
controls. The manually provisioned standalone launcher also passed real
`--record/--check` and parseable `doctor --json` with its explicit temporary
environment override. Maintained helper receipts and source defaults remained
unchanged. No dependency/lock metadata changed.

**Visual/physical-input limitation:** GNOME denied `GetWindows` and had no supported
window-control bus owner; targeted screenshot/focus was unavailable. A full-screen
screenshot returned black. No permission setup, unlock, blind keyboard input or
change to the user's desktop settings was attempted. These checks therefore do
not claim full visual/menu/physical-keyboard acceptance. Real user windows and
application sessions were left alone.

## Historical evidence

Earlier [portability validation](portability-validation.md) and
[Work portability validation](portability-validation-work-20261016.md) describe
pre-installer work and their own limits. Their former installer/license gates
are historical; this document describes the current implementation and tests.
Commit/push was separately authorized after validation; no maintained deployment
or additional live-install acceptance is implied.

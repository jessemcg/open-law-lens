# Standalone portability and setup

Open Law Lens can run from a **complete source checkout at an arbitrary path**,
without Jesse's Dropbox layout, UvEnvironments, PiRunMetrics, prior briefs or
Current Case integrations. The source installer is implemented in this checkout;
see [installation](source-install.md) and [current validation/publication status](source-install-validation.md).
It is not a self-contained wheel.
Keep the checkout: scripts, `.pi` instructions/extensions and icons are runtime
resources. Moving it requires explicit reprovisioning. No resource is downloaded
or dependency installed during launch.

## Two intentionally separate modes

- **Maintained / legacy** (default for existing callers): the existing
  UvEnvironments helper and desktop launcher continue to work. Settings,
  library, prior briefs and Research Cache remain in their existing locations.
- **Standalone**: `scripts/open-law-lens-standalone.sh` selects this mode before
  importing Python modules. It checks an explicitly provisioned local runtime
  and uses per-user XDG storage. It does not read the checkout's personal
  `config.json` or `.pi/settings.json`.

There is no automatic migration or copying between modes. Changing modes does
not move a token, library, saved answer, case file or provider authorization.
Existing private settings must not be rewritten as a deployment step.

## Supported runtime and capabilities

The current standalone runtime contract is managed **Python 3.13**, GTK >=4.10,
Libadwaita >=1.4 and PyGObject as locked in `uv.lock`. Native build dependencies
are required when uv builds PyGObject/pycairo (C compiler, pkg-config, Cairo and
GObject-introspection development packages). Package names and availability vary
by Linux distribution; a desktop with older native libraries is not made
compatible by installing a newer Python. Historical Home and Work validation runs are documented separately in the
acceptance notes; neither certifies support across Linux distributions.

| Capability | Additional prerequisites |
| --- | --- |
| Core GUI / citation reading | GTK/Libadwaita, locked Python dependencies |
| CourtListener case research | Internet and a CourtListener API token (Settings or `COURTLISTENER_TOKEN`) |
| Embedded agent workflows | VTE 3.91, Pi and its supported Node (>=22.19), authorized model/provider |
| Prior-brief indexing | `pandoc`, an existing readable ODT archive selected in Settings |
| PDF extraction | `pdftotext` |
| Scholar / LegInfo browser recovery | Supported default HTTPS browser, standalone native `computer-use-linux`, accessibility/exact window targeting, regular clipboard reader |
| Selection lookup | `wl-paste`, `xclip` or `xsel`, with actual desktop access |
| Current Case | Optional selected-case file and case roots; not required for manual fact-pattern selection |

Missing Pi, VTE or a briefs archive must not prevent ordinary citation reading.
Browser recovery is optional and must still fail closed on missing desktop
support, ambiguous identity, changed targets or a human challenge. Diagnostics
never grants desktop permissions, solves a challenge or opens a browser.

## Explicit provisioning (not launch)

For the maintained checkout on Jesse's computers, continue using the absolute
`UvEnvironments/project-env` helper. **Do not use the following recipe to replace
an existing maintained runtime.** Tests use paired `--project` and
`--environment` overrides to that helper.

For a separate, complete standalone checkout, with uv and native prerequisites
already installed, run this in a dedicated shell. Replace `source_root` with its
actual absolute path. The environment is machine-local, outside synchronized
source, and dedicated to this app:

```bash
source_root="/absolute/path/to/OpenLawLens"
environment="$HOME/.local/share/open-law-lens/environment"
env -u VIRTUAL_ENV -u PYTHONHOME -u PYTHONPATH -u UV_PYTHON \
  UV_PROJECT_ENVIRONMENT="$environment" \
  uv sync --locked --python 3.13 --project "$source_root" &&
env -u PYTHONHOME -u PYTHONPATH \
  "$environment/bin/python" "$source_root/scripts/standalone-runtime.py" --record
```

Run `--record` only after a successful explicit sync. uv installs the source
project editably; a `pip install` of a wheel alone is not this contract. Never
put an environment in Dropbox or share one between projects. Do not use bare
`uv sync` (which defaults to a source `.venv`). Do not run application code as
root. No administrator/system package changes are performed by these scripts.

The private atomic receipt records source path, environment path, Python version
and a digest of `pyproject.toml` + `uv.lock`. Launch checks the receipt and imported
source identity. A stale/missing environment fails with guidance, never a silent
install. The receipt is a consistency check, not a cryptographic source-integrity
or dependency audit. Ordinary source edits do not require sync; dependency changes
or moving a source checkout do. Never move/copy the environment itself.

## Launch and diagnose

```bash
bash "$source_root/scripts/open-law-lens-standalone.sh" doctor --json
bash "$source_root/scripts/open-law-lens-standalone.sh" app
```

The launcher accepts any normal CLI arguments, works regardless of the caller's
working directory, and supports an absolute `OPEN_LAW_LENS_ENVIRONMENT` override
for a separately provisioned runtime. It clears inherited Python/uv environment
identity. It sets `OPEN_LAW_LENS_STORAGE=standalone` and a private creation umask.
It never silently reuses a maintained runtime or falls back to system Python.

First launch without a standalone config opens **Setup / Diagnostics**. This is
also available from the app menu. It reports redacted per-capability readiness,
not a single all-or-nothing install status. Default checks do not contact a
network, invoke Pi, read documents or open browsers (they may check Node's version).

- `doctor --agent-check`: opt-in offline Pi model enumeration, no paid model call.
- `doctor --connectivity`: opt-in bounded HTTPS request to CourtListener. The token
  may be used but is never included in the report.
- `doctor` exits nonzero when core runtime/resources are missing; missing optional
  capabilities do not make core readiness fail.
- Binary/package presence is not proof of authorization, desktop permissions,
  browser accessibility or successful model output.

Install/authorize Pi separately following Pi's official instructions. Open Law
Lens does not store provider credentials or choose a provider for a new user.
Standalone model discovery ignores the tracked personal project fallback. The
single shared Agent Model selection in Settings applies to every new Agent
session; otherwise the user's Pi defaults apply. A new standalone agent launch verifies that its chosen
model is available before launching. All five profiles expose only
`read,bash,grep,find,ls`; no general web-search tool is available. Closed-corpus
workflows keep their source restrictions. Baseline extraction works without
Computer Use; the source installer includes the standalone native runtime for
Scholar/LegInfo recovery (see [setup](source-install.md#standalone-computer-use)).

## Storage and privacy

| Data | Standalone default |
| --- | --- |
| App preferences / CourtListener token | `$XDG_CONFIG_HOME/open-law-lens/config.json` |
| App-specific Pi model settings, if explicitly saved | `$XDG_CONFIG_HOME/open-law-lens/pi/settings.json` |
| Durable case library | `$XDG_DATA_HOME/open-law-lens/library/open_law_lens.sqlite3` |
| Research Cache, saved answers, highlights, research sets | `$XDG_DATA_HOME/open-law-lens/research/` |
| Default prior-brief source folder | `$XDG_DATA_HOME/open-law-lens/prior_briefs/` |
| Prior-brief indexes | `$XDG_DATA_HOME/open-law-lens/library/` |
| Agent workspaces / session transport | `$XDG_STATE_HOME/open-law-lens/agent-workspaces/` |
| Runtime requests and follow-up sockets | `$XDG_RUNTIME_DIR/open-law-lens-private/` |

Unset/relative XDG home variables use their standard absolute home defaults.
Missing/relative `XDG_RUNTIME_DIR` uses an owned private per-UID temporary
directory named `open-law-lens-UID-private` instead. This separate namespace
leaves historical directories and live session sockets alone. Unsafe existing runtime directories are rejected rather than
chmodded or followed. Saved research deliberately lives in **data**, not XDG
cache: it is not disposable HTTP data. Clearing standalone Research Cache keeps
saved answer files. No old data is migrated or deleted.

Existing explicit `OPEN_LAW_LENS_CONFIG`, `OPEN_LAW_LENS_CACHE_DIR`,
`OPEN_LAW_LENS_LIBRARY_DB`, `OPEN_LAW_LENS_PRIOR_BRIEFS_DIR` and
`OPEN_LAW_LENS_PRIOR_BRIEFS_DB` overrides retain priority. Use absolute paths.
Saved Prior Briefs Folder remains below the explicit source-folder override.
`OPEN_LAW_LENS_CURRENT_CASE_FILE` plus colon-separated absolute
`OPEN_LAW_LENS_CASE_ROOTS` enable the optional personal integration. Without
these, standalone does not inspect Jesse's case paths. The fact-pattern chooser
remains usable without that integration.

Local storage is **not** a promise of entirely local processing. CourtListener
receives case lookup/search requests. Selected facts, briefing and research
requests may be sent to the configured model provider. Browser recovery sends
public authority queries to Google Scholar or requests to official LegInfo pages. Authorize that disclosure before using private legal material.
Settings files are written privately (`0600`); no provider credentials, document
contents, raw service error prose or private file paths belong in diagnostics.

## Optional metrics and maintained integrations

Standalone disables PiRunMetrics by default and requires no sibling project.
Explicit opt-in (`PI_RUN_METRICS_ENABLED=1`) uses the existing sibling adapter
when available and stores new records in XDG state unless
`PI_RUN_METRICS_ROOT` is explicitly set. Missing metrics code remains fail-open.
Existing maintained callers retain their archive location and metrics behavior.

The maintained `Desktop_Files/launch-open-law-lens.sh` still uses
`project-env run OpenLawLens open-law-lens app`; XREMAP's `open-selected` command
uses the same helper. Neither contract needs changing for this addition. A
public installer generates its own receipt-bound standalone command and desktop
entry, not a copy of Jesse's absolute maintained desktop entry. The manual
standalone script remains supported with its original environment override/default.

## Validation

Run write-producing checks from a tracked/new-source-only disposable copy and
paired disposable environment, never from private production state. Include an
isolated sibling PiRunMetrics source for maintained metrics tests; separately
verify standalone without any sibling. `tests/test_portability.py` covers XDG
resolution, no-state diagnostics, saved answers, optional Current Case,
commands with spaces, all five confined workflow launches without sibling
projects, and ignored personal model defaults. `tests/test_standalone_runtime.py`
covers receipt acceptance/rejection and atomic private writes.
`tests/test_diagnostics_ui.py` covers redacted errors, refresh and closed-window
result ownership. `tests/preview_portability.py` exercises actual GTK startup,
missing VTE, Setup, and synthetic Settings save/reopen. It uses temporary state,
no real Pi/model/network calls; `--hold` allows local desktop inspection.

## Linux boundary and native prerequisites

GTK >=4.10 supplies `Gtk.FileDialog`; Libadwaita >=1.4 supplies `Adw.SpinRow`
and `Adw.ToolbarView`. Locked PyGObject 3.56.3/Pycairo 1.29.0 require native
build headers/pkg-config: GLib >=2.80/girepository-2.0, Cairo, libffi and a C
toolchain, plus GTK/Adwaita typelibs. Distro `python3-gi` alone is insufficient
for managed Python. Do not substitute the older girepository-1.0 development API.

Candidate apt packages: `build-essential pkg-config libcairo2-dev
libgirepository-2.0-dev libffi-dev gir1.2-gtk-4.0 gir1.2-adw-1`. Candidate dnf
packages: `gcc pkgconf-pkg-config cairo-devel gobject-introspection-devel
glib2-devel cairo-gobject-devel libffi-devel gtk4 libadwaita`. Verify names and versions on the actual
release before advertising support. Existing native build caches can mask missing
prerequisites; no clean apt/dnf provisioning acceptance is claimed.

Optional tools include VTE GTK4 (`gir1.2-vte-3.91` or `vte291-gtk4`),
`poppler-utils`, `pandoc`, `wl-clipboard` or X11 `xclip`/`xsel`. No GPU is required.
No universal browser automation or non-GNOME desktop support is promised.

## Execution boundaries and publication safeguards

Same-environment GUI children use `sys.executable`. Selected config/library are
exported to Agent commands, but Research Cache stays isolated per workspace and
prior-brief runs keep immutable snapshots. Follow-ups never retarget an existing
session after Settings changes. Ordinary standalone launches disable bytecode
writes and treat source resources as read-only. Research Sets remain in the
library; standalone cache clear also preserves answer indexes and reader
highlights/positions. Concordance and request-location overrides remain supported.

The project is licensed under [GNU GPL v3](../LICENSE), matching the companion
projects. The installer follows latest `origin/main` on a named editable branch,
records the actual commit, and never updates/resets source during resume/repair.
It ships the full `diagnostics.RESOURCES`, Python package, lock/build metadata,
scripts and unchanged icons. Public templates are exported self-contained from
Desktop_Files; users do not need that sibling repository.

Installation requires path/native confirmations and private ownership receipts.
The existing standalone provisioning receipt remains distinct from installer
ownership. Uninstall preserves private data and never removes shared Pi/Node,
packages, credentials or maintained installations. Maintenance files live only in
`$XDG_DATA_HOME/open-law-lens/installer/`, receipt/log/lock in the corresponding
XDG state `installer/`, and disposable cache in the XDG cache `installer/`.
General data/state roots contain durable work and must never be recursively removed.

The README command requires the new bootstrap/source files on the public `main`
branch; local implementation is not publication. See
[current evidence and limitations](source-install-validation.md), including
clean-native-build versus graphical-distro certification.

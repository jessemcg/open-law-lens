# Source installation

[User guide](user-guide.md) · [Development](development.md) ·
[Storage contract](portability.md) · [Current validation/publication status](source-install-validation.md)

## Install

Run as the normal desktop user, never root:

```bash
curl -fsSL https://raw.githubusercontent.com/jessemcg/open-law-lens/main/scripts/install-bootstrap.sh | bash
```

The command becomes usable with these files only after publication to the public
repository's `main` branch. This initial `curl | bash` trusts streamed repository
code. Subsequent installer/Pi files are downloaded completely before execution;
a failed or partial download is never executed. Download-first avoids executing
the initial stream (it still trusts repository code):

```bash
python3 scripts/print-install-command.py --download-first
python3 scripts/print-install-command.py --downloader wget
python3 scripts/print-install-command.py --download-first --downloader wget
```

Those commands print, but do not execute, the alternative one-line commands.
For a locally downloaded complete checkout, `bash install.sh` runs the same engine.
No Focus, RecordPrep, UvEnvironments or other sibling checkout is required.

## Platforms and native dependencies

Initial platform policy: mutable Ubuntu 24.04/26.04 or compatible Ubuntu bases,
conventional Fedora 43/44 or compatible bases, x86_64/aarch64. Immutable/rpm-ostree
systems and unsupported bases/architectures are rejected before application changes.
This is a support target, not a claim of full graphical certification on every base.

The engine previews apt/dnf transactions and asks before sudo. It refuses package
removals/unavailable dependencies, adds no repositories and does no blanket OS
upgrade. Native tools include Git, curl, system Python (maintenance only), C
compiler/build tools, pkg-config, Cairo/GObject/GLib/libffi development packages,
GTK/Adwaita/GdkPixbuf, GTK4 VTE, desktop-file/icon/XDG utilities, pandoc,
poppler-utils (`pdftotext`), wl-clipboard and xclip. Fedora requires both
`cairo-devel` **and** `cairo-gobject-devel`. Exact package sets are in
`scripts/open_law_lens_maintenance.py`.

Actual ABI/API checks require GLib/girepository 2.80+, GTK 4.10+, Libadwaita 1.4+,
`Gtk.FileDialog`, `Adw.SpinRow`, and `Adw.ToolbarView`. The unchanged `uv.lock`
provides the managed-Python PyGObject/pycairo stack, not distro Python GI alone.
Missing official repository components must be enabled explicitly by the user;
resume afterward. No GPU is required.

## Terminal flow

Eight append-only stages: platform/destinations; change/path approval; native
packages; editable Git source; uv/managed Python; locked editable dependencies
and standalone Computer Use; desktop/icons/commands; final runtime/launcher checks. The progress bar counts
completed stages, not elapsed time. Redirected output, `NO_COLOR`, and `TERM=dumb`
are plain; other terminals use Unicode or ASCII fallback. Native package output
and errors remain visible. Prompts read the controlling `/dev/tty`, not the script
stream. Run from an interactive terminal.

Ordinary path and native approvals use **Enter to continue / Ctrl+C to cancel**.
Exceptional bootstrap prerequisites (a missing downloader/system Python) require
explicit `yes`; destructive actions have separate confirmation. There is no
source viewer, authentication wizard, extra execution prompt or new-terminal handoff.

After all application checks, the engine atomically records `phase=complete`,
fills the bar, and prints **Open Law Lens is installed. Open it from your
applications menu.** Only then does optional Pi setup begin.

## Destinations and ownership

| Component | Default |
| --- | --- |
| Editable source | `~/OpenLawLens` (`--source-dir` overrides) |
| Environment | `~/.local/share/uv/project-envs/OpenLawLens` |
| Private managed Python | `~/.local/share/uv/project-python/OpenLawLens` |
| Private uv fallback | `~/.local/share/open-law-lens/tools` |
| Standalone Computer Use + native helpers | `~/.local/share/open-law-lens/tools/computer-use/` |
| App settings/token | `$XDG_CONFIG_HOME/open-law-lens/config.json` |
| Explicit app Pi preferences | `$XDG_CONFIG_HOME/open-law-lens/pi/settings.json` |
| Durable library/research/prior-brief indexes | Existing `$XDG_DATA_HOME/open-law-lens/` paths |
| Maintenance engine | `$XDG_DATA_HOME/open-law-lens/installer/` |
| Receipt/log/lock | `$XDG_STATE_HOME/open-law-lens/installer/` |
| Disposable installer/uv cache | `$XDG_CACHE_HOME/open-law-lens/installer/` |
| Commands | `~/.local/bin/open-law-lens`, `~/.local/bin/open-law-lens-uninstall` |
| Desktop identity | `com.mcglaw.OpenLawLens` |

XDG variables normally mean `~/.config`, `~/.local/share`, `~/.local/state`, and
`~/.cache`. Installer ownership roots must be absolute, machine-local under HOME
(except configurable source), non-overlapping, with trusted non-symlink ancestors.
Runtime stores must never be synchronized. An existing unowned source checkout,
environment, tool store, command, desktop entry or icon blocks installation.
This includes Jesse's identically named maintained environment: **no adoption,
repair, deletion or relocation**. Choose a separate user for public acceptance
when its default environment is already maintained.

Existing XDG settings/data may be reused but are not installer-owned. Installation
does not create/seed `config.json`, copy a CourtListener token or personal model
fallback, select models, migrate research, or follow referenced document locations.
Explicit documented app data overrides retain priority. Private ownership receipts,
resource markers, locks and installed-file hashes prevent blind takeover/removal.
The standalone dependency/source receipt (`.open-law-lens-runtime.json`) is
separate from the installer's ownership receipt.

A suitable uv is reused; otherwise private uv **0.11.8** is downloaded from Astral.
Managed Python 3.13 and `uv sync --locked` explicitly provision an editable project
outside source. No checkout `.venv`, system pip, sudo npm, launch-time install,
Git update, lock rewrite or Python download occurs during ordinary launch.

## Resume and repair

```bash
curl -fsSL https://raw.githubusercontent.com/jessemcg/open-law-lens/main/scripts/install-bootstrap.sh | bash -s -- --resume
bash install.sh --dry-run --source-dir "$HOME/another source"
bash install.sh --resume
bash install.sh --repair
```

Resume without a source argument uses the receipt-bound source. Fresh source uses
`open-law-lens-install` based on latest `origin/main`, recording its actual commit.
Resume/repair revalidate native/source/runtime/integration stages but never fetch,
reset, clean, stash, rewrite the lock, or discard local source edits. Repair is
not an update command. Changed installed command/icon/desktop files block repair
or removal rather than being overwritten silently.

A failed stage retains attributable resources and reports resume/removal commands.
Durable maintenance plus the uninstall command are installed before source cloning
or dependency builds, so even those failures are removable. Native additions are
recorded, not silently rolled back. Concurrent maintenance is rejected. Close the
app/embedded sessions before removal; the engine reports active use and never kills it.

## Optional Pi

Existing Pi is retained, not upgraded. If absent, **Enter installs / `skip` declines**.
The official `https://pi.dev/install.sh` is fully downloaded, then runs in the same
controlling terminal. Pi is rediscovered immediately, including
`$PI_CODING_AGENT_DIR/bin/pi`; no shell restart is needed. The effective Pi directory
defaults to `~/.pi/agent`. Node discovery supports official
`$XDG_DATA_HOME/pi-node/current/bin` and the standard HOME fallback plus legacy
version stores. Official shell launchers run directly; only JavaScript entrypoints
use bundled Node argv. Explicit executable overrides and PATH installations remain.

There are no supporting agent-package offers or package operations. Skip, EOF,
Ctrl+C or discovery/network failure never changes application completion or its
success exit status. Ctrl+C ends optional setup. Existing shared packages/settings
are not inspected, reconciled, updated or removed.

Run `/login` in Pi separately, then select available models in Open Law Lens
Settings. No login, model prompt or paid test runs automatically. All five
embedded workflows use `read,bash,grep,find,ls`, with only the app-owned follow-up
bridge and optional passive metrics observer explicitly loaded. No general
web-search tool or model-facing desktop control is exposed. Unresolved source or
identity gaps are reported, not filled through general web search.

## Standalone Computer Use

The installer downloads **Computer Use 0.7.18** directly from the upstream
[GitHub release](https://github.com/agent-sh/computer-use-linux/releases/tag/v0.7.18),
independently of Pi, npm and Node. It installs the native server,
`computer-use-linux-cosmic` targeting helper and `computer-use-linux-indicator`
activity overlay together under the private tools directory. x86_64 and aarch64
assets have architecture-specific, source-pinned SHA256 checksums. Complete
HTTPS downloads are verified as native ELF files before any is published or run;
partial/corrupt downloads stop the dependency stage and can be resumed. A read-only
`--help` smoke check must pass before application completion.

The ownership receipt records all three hashes and the pinned version. Repair
reuses matching files without redownloading, rejects modified/unowned files, and
can explicitly provision the version pinned by the current source. No automatic
update or launch-time installation occurs. Normal uninstall removes this
app-owned runtime, never a separately installed executable or shared agent package.
Changing the pin requires reviewing upstream assets, checksums and recovery
compatibility. This independently downloaded upstream runtime retains its own license.

Resolution order is `OPEN_LAW_LENS_COMPUTER_USE_BIN` (explicit executable), the
app-owned path, then standalone `computer-use-linux` on PATH. Node launchers are
rejected. There is no agent package-directory discovery. For a manually
provisioned/maintained installation, install an upstream standalone binary with
its helpers separately and set the override or PATH; the maintained Python helper
does not provision this native runtime. An existing agent package is not adopted
or uninstalled, and this change does not deploy binaries into maintained runtimes.

The existing bounded Python stdio MCP client and deterministic Scholar/LegInfo
state machines remain in place: no Pi/model process is needed for recovery.
Installing the binary is **not** desktop/browser readiness. In your normal
local desktop session, inspect readiness manually:

```bash
"$HOME/.local/share/open-law-lens/tools/computer-use/computer-use-linux" doctor
```

Follow the upstream [setup guide](https://github.com/agent-sh/computer-use-linux)
for supported browser accessibility, exact-window targeting and keyboard input.
GNOME Wayland may require its companion **GNOME Shell** extension (not an agent
extension) and a manual logout/login; that is not a universal Linux requirement.
The installer never grants desktop permissions, changes GNOME extensions, opens
a browser or bypasses a human verification challenge. Setup commands have desktop
effects; review them before running. `open-law-lens doctor` or **Setup / Diagnostics**
provides redacted local checks without starting browser recovery or network/model
probes by default. Missing readiness fails recovery closed, not baseline reading.

## Development helper

```bash
scripts/open-law-lens-env check
scripts/open-law-lens-env sync
scripts/open-law-lens-env run open-law-lens doctor --json
scripts/open-law-lens-env run python -m unittest discover -s tests
```

`check` validates receipt/source/native resources/dependency binding. Only `sync`
provisions. `run` verifies and directly executes an installed environment command,
with isolated runtime identity, private permissions and bytecode suppression.
Ordinary source edits are immediately visible. Moving source or changing the
build/lock contract requires explicit sync; never move/copy the environment.
The manually provisioned `scripts/open-law-lens-standalone.sh` keeps its original
`OPEN_LAW_LENS_ENVIRONMENT` override/default; public installation binds its chosen
environment explicitly. Maintained callers still default to legacy storage and
UvEnvironments; no maintained desktop/XREMAP contract is changed.

## Removal

Close the application and embedded sessions:

```bash
"$HOME/.local/bin/open-law-lens-uninstall" --dry-run
"$HOME/.local/bin/open-law-lens-uninstall"
"$HOME/.local/bin/open-law-lens-uninstall" --dry-run --purge
"$HOME/.local/bin/open-law-lens-uninstall" --purge
```

Normal removal requires `yes` and deletes only receipt-owned environment, private
Python/tools, commands, desktop/icons and disposable installer cache. Source,
settings, library/research/answers/highlights, research sets, prior-brief indexes,
agent sessions, external legal documents and Pi remain. Maintenance is retained
for later purge; it can also be invoked directly with `/usr/bin/python3 -I`.

Purge separately requires **exact path** consent for eligible installer-created
source and maintenance records. It reports source edits, ignored files, local
branches and commits not represented by remote refs. Recognized runtime/research
or legal-document content blocks source purge. Pre-existing/unowned or modified
installed files block deletion. This installer does not seed/own settings, so
settings remain even with purge. It never recursively deletes the general
`open-law-lens` data/state roots or follows document references.

`--purge --cleanup-packages` optionally previews only recorded introduced native
packages with separate `yes` approvals and conservative removal-set checks; no
autoremove. Shared Pi, Node, packages, credentials and sessions are never removed.
To remove Pi separately, follow its official installer menu:

```bash
curl -fsSL https://pi.dev/install.sh | sh
```

Choose **Uninstall Pi** only after considering other apps that use it. Its
credentials/sessions remain; no app installer should delete them automatically.

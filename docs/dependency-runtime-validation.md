# Standalone recovery runtime revision — 2026-10-17

This follow-up replaces agent-package provisioning with a standalone native
Computer Use download and removes the general web-search integration. The owner
authorized source publication after local validation; that does not certify a
live public installation. The [initial installer validation](source-install-validation.md)
remains historical evidence for native Python builds and distro lifecycle behavior;
those guest runs predate this revision and do not certify the new binary stage.

## Implementation boundaries

- Automated Google Scholar recovery and the LegInfo 403 fallback remain on the
  existing bounded Python stdio MCP client/state machines. No replacement with
  model-selected desktop actions, Pi orchestration or code mode.
- Install/repair downloads pinned Computer Use 0.7.18 native server, COSMIC helper
  and activity indicator assets. Architecture-specific source-pinned SHA256 and
  ELF checks precede publication/execution; the server's `--help` check precedes
  application completion. No Pi, npm or Node is needed for this native runtime.
- Ownership/hash records include the three native files. Matching repair avoids
  downloads; existing schema-1 receipts without them can add them during explicit
  repair without updating source or adopting an unowned runtime. Corrupt/partial
  downloads and native launch failures stop the dependency stage, not masquerade
  as a successful install. Modified/unowned/symlink/hardlink collisions fail closed.
- No supporting agent-package offers, settings/package inspection or package
  operations. Optional Pi installation still follows the completed application
  receipt and success message. Shared packages and private preferences are retained.
- All five embedded profiles expose exactly `read,bash,grep,find,ls`; only the
  app-owned follow-up bridge and optional passive metrics observer are explicitly
  loaded. The old web override is inert, no provider credentials are requested,
  and missing metadata/source evidence is disclosed rather than searched generally.

## Checks on the current Home computer

All write-producing tests used tracked/intentionally-new source in
`/tmp/oll-native-validation-XfvFTw/source`, its paired managed-Python 3.13 environment
and synthetic HOME/XDG/Pi/storage. No production environment was synchronized.

- Full suite with a tracked-source-only PiRunMetrics sibling: **1,204 PASS**, including
  offline installed-Pi SDK acceptance with a synthetic provider and forbidden network.
- Without siblings: **1,204 run, 1,202 PASS, 2 expected optional-observer skips**.
- Native runtime tests cover both architecture manifests, all three owned files,
  no-download repair, older receipts, publication recovery, hash/ELF rejection,
  partial downloads, native smoke failures/resume, collisions, modified-file refusal,
  removal and shared-agent-package preservation. Existing Scholar/LegInfo tests and
  all five confined launch profiles also pass.
- Real x86_64 release downloads passed all three pinned hashes, native ELF checks,
  server `--help`, app resolution with no Pi/Node/PATH, and a second real native
  repair with the downloader forbidden. During these isolated checks, the files
  were installed only into the disposable HOME. Subsequent separately authorized
  maintained provisioning is recorded below.
- Real aarch64 release downloads passed all three pinned hashes/ELF checks on this
  computer; **no aarch64 executable was run**. This is asset verification, not ARM
  runtime or desktop certification.
- The actual synthetic reader/Setup/Settings harness passed missing-Pi/VTE startup,
  synthetic 0600 Settings save/reopen and unconfigured Current Case checks. PID-scoped
  AT-SPI observation confirmed the new standalone-runtime guidance and absence of
  the removed web capability. No complete visual/screenshot acceptance is claimed:
  screenshot attempts met multi-window/focus-target restrictions. Only the identified
  synthetic process was stopped, and its temporary settings were removed.
- Python source compilation without bytecode, shell syntax, local documentation
  links, canonical desktop-template checks and `git diff --check` pass. Build metadata
  and `uv.lock` remain unchanged. Maintained desktop/XREMAP commands need no changes.

No live Scholar/CAPTCHA/LegInfo recovery, new desktop permission setup, distro
reinstallation, real Pi installation, paid provider call, maintained app restart,
private data migration or other-computer operation was performed. An existing
maintained/manual installation needs an independently provisioned standalone binary
and helpers (the recognized private path, PATH or
`OPEN_LAW_LENS_COMPUTER_USE_BIN`) before its next recovery; it no longer discovers
an agent-owned Node wrapper. The source installer must not be used to adopt or
repair Jesse's maintained Python environment. See
[installation and browser setup](source-install.md#standalone-computer-use).

## Subsequent authorized Home provisioning

At the owner's explicit request, the three pinned x86_64 native binaries were
subsequently downloaded and installed under
`~/.local/share/open-law-lens/tools/computer-use/` on Home. All SHA256/ELF checks
and a bounded `--help` smoke passed before publication into that new directory.
The maintained `project-env run OpenLawLens` interpreter confirmed automatic
selection of this exact native server, without a PATH or preference change.
The installed native CLI `doctor` exited zero: MCP registration, accessibility,
window querying and keyboard input were ready, with no blockers. Screenshot
capture remained unverified; no screenshot or live Scholar recovery was attempted.
No public installer, Python synchronization, shared Pi-package change, permission
setup, application restart or other-computer operation was involved. These
machine-local executables are not included in the source commit.

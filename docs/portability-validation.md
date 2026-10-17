# Portability acceptance

Historical pre-installer evidence. See [current installer validation and publication
status](source-install-validation.md) for the shipped installer and GPL v3 decision.

## Conflict reconciliation — Work, 2026-10-17

Reconciled six Dropbox source/documentation conflicts locally on Work. Preserved
Home's atomic private receipt replacement, executable/virtual-environment checks,
relative-XDG tests and diagnostics UI tests; restored Work's native API/resource
checks, optional-capability and model-no-substitution tests. Corrected the Home
runtime safety test and documentation to use the actual `open-law-lens-private`
namespace. Both versions' provisioning and publication safeguards are retained.

Merged-source validation on Work: **1,153 unittest tests PASS** in a fresh
tracked/new-source-only disposable checkout with its own locked managed-Python
3.13 environment and a tracked-source PiRunMetrics fixture. Added regression
coverage rejects missing native APIs/resources for both record and check without
changing the existing receipt. Shell syntax and `git diff --check` PASS. No new
GUI behavior was introduced or desktop acceptance repeated. No private runtime
files, maintained environment, running app, or other computer were modified.
Six merged conflict copies were removed only after byte-for-byte backup checks;
older private-data and Git-metadata conflicts remain untouched.

The original Work acceptance report is preserved separately in
[Work validation, October 16](portability-validation-work-20261016.md). The Home
report below is historical evidence from that session, not validation performed
on another computer during this reconciliation.

## Historical Home acceptance — 2026-10-17

Validation ran **only on Home**, from disposable complete-source copies and
paired machine-local test environments. No production settings, research data,
case materials or provider credentials were copied or rewritten. No other
computer was contacted, no model request was made, and no release was published.

## Automated suite

- Full `unittest discover -s tests`: **1,149 tests, OK** (15.556 seconds).
- Maintained-mode coverage included a tracked-source-only disposable sibling
  PiRunMetrics. Without that optional test fixture, five maintained metrics
  subtests fail because their adapter cannot be loaded; this is not the
  standalone runtime's dependency contract.
- Portability tests exercise XDG/legacy separation, read-only path resolution,
  explicit overrides and relative-XDG fallback, optional Current Case,
  private configuration writes, saved-answer preservation, all five workflow
  wrappers with no sibling/uv/Computer Use requirement, literal quoted commands
  with spaces, standalone model-discovery isolation, and unsafe runtime-directory
  rejection without repairing unrelated paths.
- Additional receipt tests cover record/check, stale dependency digests,
  wrong-source/incomplete/system-runtime refusal, private atomic replacement and
  preserving a symlink target.
- Additional diagnostics UI tests cover redacted failed probes, stale-copy
  clearing, current successful results and ignoring results after close.

## Real standalone launcher smoke test

A second complete-source copy was installed in a path containing spaces, with a
separate environment also containing spaces. Explicit provisioning used the
UvEnvironments helper's paired disposable overrides (same locked editable source
contract), followed by `standalone-runtime.py --record`. The source's parent
contained **neither UvEnvironments nor PiRunMetrics**.

With a synthetic HOME/Pi configuration, fresh explicit XDG roots, an arbitrary
`/tmp` working directory and launch PATH limited to `/usr/bin:/bin` (no uv):

- Missing provisioning receipt refused launch with explicit setup guidance.
- Recorded environment passed the actual standalone launcher.
- `doctor --json` reported standalone/core ready and optional Pi missing.
- Default diagnostics created no config/data directories.
- `cache-dir`, `library-db`, `show-cache` and `--help` succeeded through the
  installed executable, not a source-module shortcut.
- A changed disposable lockfile invalidated the receipt; restoring its bytes
  restored acceptance without installing anything during launch.
- Hashes of every source file were unchanged after these checks.

## Native GUI acceptance

`tests/preview_portability.py --hold` passed startup without VTE, optional
unconfigured Current Case, Setup readiness, private synthetic Settings save and
reopen. The actual Setup window was inspected locally through Linux Computer
Use (accessibility tree and screenshot). It showed core readiness, missing
optional Pi capability, redacted token status, opt-in checks and privacy guidance.
Only the synthetic test window was repositioned for inspection, then its owned
process was stopped. No user application was restarted.

## Scope and limitations

This accepts the portability groundwork, **not** a published public installer or
cross-distribution certification. No paid end-to-end research, browser recovery,
provider login, real case operation, system dependency installation, maintained
runtime sync or external desktop interaction was performed. Existing maintained
Desktop_Files and XREMAP callers still select OpenLawLens via project-env, so no
cross-repository change was needed. Legacy settings/library/cache paths remain
compatible; standalone data starts separately, without migration.

See [standalone setup](portability.md) for the future installer's release pinning,
native prerequisites, desktop integration, transactional updates/recovery and
private-data-preserving uninstall requirements.

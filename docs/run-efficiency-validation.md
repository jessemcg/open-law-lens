# Run reliability and local efficiency validation

## Scope and evidence limits

Implemented on **Home only**, starting from `4979082`. No private transcripts,
real opinions/briefs, settings, libraries, reports or credentials were inspected
for this work. The supplied ten-run descriptive report is not a controlled
comparison and does not establish historical defect incidence or answer quality.
No paid model was invoked. No models, reasoning, tool lists, web permissions,
research floors/ceilings or launch interfaces changed. PiRunMetrics, Desktop_Files,
XREMAP, shared Pi configuration and other computers were not modified.

The pre-existing untracked `prior_briefs.sqlite3` and conflicted reader test copy
were excluded from the disposable checkout and left untouched. There is no data,
schema or saved-answer migration. Existing answers remain readable.

## Contracts

### Completed answers

`PiSessionSnapshotCache` makes one streaming JSONL pass per changed file and caches
by path/device/inode/size/nanosecond mtime. Complete newline-terminated records
alone are accepted; a partial tail is retried when the file changes. A concurrent
change during parsing makes the snapshot ineligible until a stable recheck.
Replacement and truncation rebuild state; each window generation owns a new cache.

Only assistant text with `stopReason: stop` and no tool-call content completes a
request. IDs identify user/assistant entries, with deterministic record ordinals
for old fixtures. Earlier successes remain reference output; failed/pending current
requests select Session and show **Previous Answer** when an earlier answer exists.
Save is disabled and its handler separately checks eligibility, finishing/submission
state and the log's current stat signature. A zero shell exit never authorizes an
incomplete answer. No retry/replay was added. Unchanged polls do not steal a user's
Answer/Session selection or repeatedly display the same failure status.

### Citation lookup

A whole-input, supported bare official reporter citation goes directly to the
existing Library/cache/CourtListener path. Names, mixed citations, pinpoints,
placeholders, malformed numbers and unsupported reporters keep the suggestion
fallback. Name identity, refresh, reconciliation, publication, pagination and
Scholar recovery behavior remain unchanged.

Suggestion enumeration opts out of timestamp writes through keyword-only getter
options; ordinary callers retain touching defaults. Optional concordance loaders
accept `None`. Candidate selection still requires qualifying official pagination.

### Full-source artifacts

`extract-case` (full opinion only) and `extract-brief` accept
`--output-dir ABSOLUTE_NEW_DIRECTORY`, mutually exclusive with `--text` and, for
cases, `--find`. Existing output modes are unchanged. The destination's parents
must exist. Embedded destinations must be strictly inside
`OPEN_LAW_LENS_AGENT_WORKSPACE`.

A successful export exclusively creates a 0700 directory with 0600 files:

- `metadata.json`: existing metadata/provenance/warnings/pagination, no body;
- `manifest.json`: version 1, ordered parts, exact zero-based Unicode-character
  start/end offsets (end exclusive), UTF-8 byte counts and line counts;
- `part-0001.txt`, etc.: contiguous unmodified text, at most 32 KiB UTF-8 and
  1,500 LF-delimited lines, including the trailing empty line Pi read counts.

All filesystem operations use held no-follow directory descriptors. Existing
paths, symlink traversal, relative paths and workspace escapes fail. Success is
published only after every file is written and the destination identity is checked.
Failures return nonzero structured JSON and remove only this invocation's incomplete
files/directory. Export never converts failed extraction or an unpaginated baseline
into verified authority. Chunk numbers are **not reporter pinpoints**.

Stdout is bounded export status/locations/counts, not body or a chunk list. Detailed
diagnostics remain in metadata/manifest. Artifacts use the existing private workspace
lifecycle; nothing is copied into metrics archives and no fingerprints are generated.

Compact `extract-case --find` remains preferred for narrow propositions. Prior Briefs
fetches a selected document once to an artifact and must read every part before
reliance; metadata/grep are not full inspection. Full-source inspection does not
reduce the number of source tokens that must be delivered. Only exact recognized
shipped prompt defaults upgrade in memory; customized prose and all profiles survive,
and loading does not write `config.json`.

## Managed runtime and isolation

Production `project-env check OpenLawLens` passed. The previously blocked fresh
build was resolved using **available cached, lock-matching prebuilt dependency
artifacts**, not distro Python/GI, environment copying, lock edits or system package
installation. Explicit helper provisioning into `/tmp/oll-efficiency-3FmLdI/env`
succeeded: managed Python 3.13.12, locked PyGObject 3.56.3 / pycairo 1.29.0. Native
GTK previews also used this disposable managed environment. Production was not synced
or changed. All test data/config/caches were disposable and machine-local.

The existing metrics SDK tests require a read-only copy of the sibling's tracked
source beside the disposable checkout; that is a test dependency, not a metrics
implementation/deployment change.

## Measurements (single synthetic runs, not statistical comparisons)

Fixed synthetic libraries: 0/20/200 officially paginated cases; no network lookup.
Citation numbers below measure **resolution stage only**, before direct retrieval.
SQLite trace counts include transaction statements.

| Stage | Baseline ms | Changed ms | Baseline SQL / updates | Changed SQL / updates |
|---|---:|---:|---:|---:|
| Bare citation, 0 cases | 0.297 | 0.089 | 1 / 0 | 0 / 0 |
| Bare citation, 20 cases | 10.000 | 0.085 | 201 / 40 | 0 / 0 |
| Bare citation, 200 cases | 101.170 | 0.067 | 2,001 / 400 | 0 / 0 |
| Suggestions, 20 cases | 9.790 | 8.143 | 201 / 40 | 81 / 0 |
| Suggestions, 200 cases | 85.175 | 76.561 | 2,001 / 400 | 801 / 0 |

Candidate counts/order remain unchanged. A separate regression holds a SQLite
`BEGIN IMMEDIATE` write reservation while suggestions/name resolution succeed
without any writes. The 200-case scan still examines opinions; it was not replaced
with a weaker pagination test or a schema change.

A 10,000,091-byte synthetic session, warmed once, then polled ten times:

- Baseline: **20 full reads / 20 JSON record parses, 416.301 ms**.
- Changed: **0 reads / 0 parses, 0.023 ms** (stat checks only).
- One subsequent changed poll with two records: baseline 2 full reads/4 parses;
  changed 1 streaming read/2 record parses. This means one pass, not one JSON
  decode regardless of record count.

Long-source transport, installed **Pi 1.0.4** read tool, offline (no Pi session):

- 126,070-byte synthetic single-line opinion plus a late exception;
- default indented JSON source transport truncates;
- one artifact extraction, **4 part reads, all 126,070 bytes delivered exactly**;
- export 0.343 ms; bounded status JSON 290 bytes in the harness's serialization;
- part delivery 1.294 ms. Unicode/10,000-short-line fixtures also reassemble exactly.

These are local lookup/poll/export/transport measurements. They neither explain
minute-long research sessions nor promise end-to-end speed, cost, token savings,
quotation fidelity in generated answers or legal accuracy.

## Acceptance

- Full documented unittest suite: **1,143 tests, no failures or skips** (final rerun).
  This includes real installed offline SDK/wrapper fixtures for all five workflows,
  enabled/disabled/missing/unwritable collector variants, unchanged available tools
  and synthetic model selection/context, real JSONL transport, provider error then
  successful retry, identical successful follow-ups and isolated session lifecycle.
  Local Search Briefs still launches no Pi run. Production profiles remain untouched.
- Compilation of package/tests and `git diff --check`: PASS.
- Focused tests cover every non-completing reason, tool-call content, identical text
  with distinct identities, partial writes, replacement/truncation, worker/exit
  rechecks, stale generations, Save-handler refusal, changed-before-poll refusal,
  navigation retention, truncated-log turn-count resets, reference-render/cached-exit
  spinner cleanup, optional concordance, conservative fast-path negatives,
  read reservations, export failure/permissions, existing destinations, symlinks,
  workspace escapes, long lines, Unicode, paragraph/part boundaries and late text.
- Native Computer Use against separately identified **Synthetic OpenLawLens — Run
  Reliability**: success; actual Save into temporary Research Cache; fresh partial
  abort; failed follow-up retaining Previous Answer with Save disabled; error;
  output limit; successful identical follow-ups; recovery after failure; replacing
  and closing while a delayed worker finishes. Guard assertions passed and all
  preview processes were stopped. No production GUI was restarted or closed.
- Screenshots/AT-SPI showed Answer/Session navigation and disabled Save for failures.
  During later reruns the local GNOME window-introspection bus became unavailable;
  exact AT-SPI actions and synthetic application readbacks remained usable. No
  desktop setup/settings repair was attempted. Final rerun included continuous
  unchanged polling and synthetic terminal partial text.
- Managed-runtime responsiveness preview: 300 paragraphs/links rendered, spinner
  through worker/batches, maximum heartbeat gap **0.025 seconds** with an injected
  one-second worker delay and exit-during-poll recheck. Not a research-duration test.

Local evidence: `/tmp/oll-efficiency-3FmLdI/` (baseline/after JSON, suite and synthetic
GUI logs). No real legal material is present. Measurements are repeatable through
`tests/run_efficiency_harness.py`; `tests/source_transport.mjs` calls the installed
read tool without loading authorization or contacting a provider.

## Reproduce locally (no other computers, no paid models)

Use an isolated candidate copy, not production settings or environment. Before
committing, include only the task's new files; exclude the unrelated untracked data:

```sh
P="$PWD/../UvEnvironments/project-env"
D=$(mktemp -d /tmp/oll-validation-XXXXXX)
mkdir "$D/source" "$D/baseline" "$D/PiRunMetrics"
git archive HEAD | tar -x -C "$D/baseline"
git ls-files -z --cached --others --exclude-standard -- . \
  ':!prior_briefs.sqlite3' ':!tests/*conflicted copy*' \
  | tar --null -T - -cf - | tar -xf - -C "$D/source"
git -C ../PiRunMetrics archive HEAD | tar -x -C "$D/PiRunMetrics"
"$P" --project "$D/source" --environment "$D/env" sync OpenLawLens
export OPEN_LAW_LENS_CONFIG="$D/config.json"
export OPEN_LAW_LENS_CACHE_DIR="$D/cache"
export OPEN_LAW_LENS_LIBRARY_DB="$D/library.sqlite3"
export OPEN_LAW_LENS_PRIOR_BRIEFS_DB="$D/briefs.sqlite3"
export OPEN_LAW_LENS_PRIOR_BRIEFS_DIR="$D/brief-archive"
export XDG_STATE_HOME="$D/state"
unset COURTLISTENER_TOKEN
"$P" --project "$D/source" --environment "$D/env" run OpenLawLens python -m unittest discover -s tests
"$P" --project "$D/source" --environment "$D/env" run OpenLawLens python -m compileall -q open_law_lens tests
"$P" --project "$D/source" --environment "$D/env" run OpenLawLens python tests/run_efficiency_harness.py --source "$D/baseline"
"$P" --project "$D/source" --environment "$D/env" run OpenLawLens python tests/run_efficiency_harness.py
"$P" --project "$D/source" --environment "$D/env" run OpenLawLens python tests/preview_run_reliability.py
git diff --check
```

Observe the synthetic window with native Computer Use; use the clearly labeled
scenario controls, actual Save (not Save Research Set), and Answer/Session tabs.
The Close worker control holds the test process until the stale worker finishes.
Never use the normal app's sources/settings to substitute for these tests. Missing
locked build dependencies require suitable local artifacts/prerequisites, not a
production-environment fallback or a lockfile workaround.

## Compatibility, deployment and rollback

Restart Open Law Lens when no research session is active and start fresh embedded
sessions to load the code/prompts. Do not interrupt active work. No launcher, app ID,
D-Bus action, model or tool-permission deployment is required.

Rollback only task source/prompt changes. Retain settings, libraries, caches, saved
answers, reports and metrics archives; do not repair/relabel historical results.
[Prior Brief quality failures](prior-brief-quality-acceptance.md) and
[General Law quality limitations](general-law-quality-acceptance.md) remain unchanged.
Parser and transport tests do not demonstrate improved legal reasoning or calibrated
confidence. A future paid model comparison needs separate authorization and a limit.

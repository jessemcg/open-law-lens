# Targeted session-efficiency validation

2026-11-04 UTC; Home computer only. Starting revision `ed896cc`; the pre-existing
untracked `.config.json.writer.lock` was left untouched. Two independent changes,
not a workflow redesign. README, dependencies, settings, documents, saved answers,
models, metrics and other repositories are unchanged.

## Evidence and limits

The supplied planning report describes 17 finished runs (15 completed, one error,
one aborted) in October 21–November 4, with sparse, unmatched cohorts. Aggregate
output tokens are not final-answer length; tool counts are not redundant-search
counts. These data do not establish recurring over-searching, inaccurate answers,
improper access denials, lost useful answers, or a causal performance improvement.
No private transcripts, prompts, answers or source documents were inspected here.

The concrete interface inconsistency was the treatment request's plain full-source
`extract-case` template, despite shared instructions recommending `--output-dir`
to avoid truncated JSON transport. Planning's synthetic 135,304-byte probe used a
retrieval stand-in, not the full CLI/backend: ordinary stdout was not directly
usable, while artifact parts reconstructed exactly. That establishes transport
risk/remedy, not historical incidence or legal accuracy.

## 1. Treatment full-source transport

`agent_prompts.treatment_request` keeps its signature and six named command slots.
Only `full_extract_command` changes: `mktemp -d` creates a unique parent under
`OPEN_LAW_LENS_AGENT_WORKSPACE`; the existing `agent_cli_command` supplies the
quoted CLI prefix and `extract-case --cluster-id "<cluster_id>" --output-dir
"$full_source_parent/source"`. The created parent is **not** the export destination;
its `source` child must be new. `&&` prevents extraction if directory creation fails.

The treatment skill explains bounded status JSON, metadata/manifest and lossless
parts, inspection of relevant text and surrounding qualifications, and reuse of
sufficient inspected artifacts. Directory creation/export/read failures preserve
useful compact baselines and permit a qualified supported answer. They do not
restart discovery or official-copy recovery, or license unsupported treatment.

Compact-first work, discovery ceilings, at-most-one ordinary full extraction per
case, recovery limits, verification, returned URLs, workspace containment,
exclusive writes, access permissions and public CLI syntax remain unchanged.
Delivering previously omitted evidence may increase tokens; there is no promised
net speedup and no new runtime read-completeness or answer-quality gate.

## 2. Proportionate simple definitions

Only Legal Researcher's simple-definition bullet changes: short direct definition,
material statutory routes/qualifications and required source support, with expansion
when needed, rather than the former 350–650-word target. No replacement numeric
cap, fixed paragraph count, drafting pass or automatic shortening was added.
Decisive exceptions, contrary authority and uncertainty must remain. Mandatory
case research, bounded recovery/disclosed gaps, exact quotations, title/subtitle
limits and Case Assessment structure are unchanged.

Instruction-contract tests establish this wording, not improved answers, fewer
searches, lower latency or reduced reasoning work. Behavioral benefit remains
unmeasured. No paid quality runs, new telemetry or runtime scorers were added.

## Isolated implementation acceptance

Disposable root: `/tmp/oll-targeted.qQ95S6`. Copied only Git-listed OpenLawLens
source and a read-only test copy of the sibling PiRunMetrics source. No private
runtime directories were copied. Absolute UvEnvironments `project-env` calls used
paired `--project /tmp/oll-targeted.qQ95S6/OpenLawLens` and
`--environment /tmp/oll-targeted.qQ95S6/env` overrides for provisioning/execution.
Available lock-matching cached artifacts provisioned managed Python 3.13.12,
PyGObject 3.56.3 and pycairo 1.29.0; no system prerequisites or production
environments were changed. HOME/config/data/cache/state/Pi paths were temporary.

- Generated-command regression: all six slots, unchanged five other commands;
  actual Bash execution with a synthetic executable, spaced workspace/executable
  paths and shell-safe substituted metacharacters/Unicode. One extraction per
  execution; template reuse creates distinct private parents/new children and
  preserves previous artifacts. Failed `mktemp` never invokes extraction.
- Actual CLI/exporter with mocked cluster retrieval, and installed native Pi read
  tool: **126,100- and 330,071-byte** synthetic sources, including Unicode, many
  lines, opening rules and late material qualifications, delivered exactly through
  untruncated parts. One mocked extraction each; stdout under 1,000 bytes without
  source text/chunk lists; metadata preserves warnings, URL, provenance and
  pagination status. Existing offset/byte/line-boundary tests remain intact.
- Actual export write failure cleans only its own incomplete artifact; existing
  destinations reject writes without modifying prior files. Compact fixtures stay
  intact. HTTP is explicitly forbidden in the artifact/transport acceptance tests.
- Actual wrapper assembles all five workflows once in their established order.
  Offline SDK metrics/passivity, tool confinement and follow-up checks pass.
- Synthetic tool-error session followed by a short qualified final `stop` answer
  takes the normal completed-answer/render path. No citation count, source score,
  confidence or length threshold is needed. Existing incomplete-turn,
  previous-answer and stale-generation protections pass unchanged.
- Full documented unittest discovery: **1,255 tests, 1,249 passed, 6 expected
  owner-specific skips**. Package/test Python compilation, shell syntax and
  `git diff --check` pass. No GUI changes or production app/session restart.

Initial development runs were not acceptance: the runner needed a private umask,
a cache override compatible with an existing default-path test and a disposable
Git fixture. An incorrect cluster-retrieval mock also allowed unintended retrieval
attempts for a synthetic ID; those failed and supplied no source evidence. The
corrected tests mock the actual cluster path and explicitly deny HTTP. A collision
assertion was corrected to the existing contract (export refuses writes; retrieval
may already have occurred), without changing production CLI behavior.
Local logs: `provision.log`, `full-suite-final.log` and `syntax.log` under the
above disposable root. No live legal research or paid model calls were used.

## Rollout and independent rollback

No migrations or deployment/launcher changes. After any active research session
finishes, a normal application restart gives new sessions the updated instructions;
do not interrupt sessions or rewrite saved answers.

The transport change consists of the request-builder template, treatment skill,
transport/fallback tests and its mapping/documentation. The concision change consists
of the single Legal Researcher bullet, its separate workflow-contract test and its
mapping/documentation. Either can be reverted independently; shared test/doc files
have separate methods/sections. Rollback changes only these source/instruction/test
blocks and preserves user work, private files and metrics archives.

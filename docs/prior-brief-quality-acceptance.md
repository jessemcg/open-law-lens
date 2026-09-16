# Prior Brief quality acceptance — 2026-09-15

## Result

**Implementation/static checks pass; behavioral and efficiency acceptance FAIL.**
Do not interpret prompt-string tests as evidence of reliable source inspection,
legal calibration, or faster research. No model/reasoning settings, private
configuration, archive contents, schema, launcher, XREMAP, or General Law workflow
were changed. No application restart or existing Agent-session mutation occurred.

## Implemented contract

- Prior Brief default: rank useful documents, attribute advocacy, separate
  dependent-child/adult/nondependent contexts and trial burden/appellate review,
  inspect complete selected text, preserve exact linked 2–10-word quotes, retain
  complete metadata, and describe query coverage narrowly.
- Explicit disposable-workspace-only extraction permission resolves the system
  prompt's default prohibition on writes. Fetch once, then bounded `read` chunks
  to EOF; grep is navigation, not verification. This is a prompt requirement,
  **not an enforced reading ledger**.
- `PriorBriefSearchPage(results, limit, has_more)` executes the existing query
  with the clamped limit plus one. Ranking, match construction, result fields,
  default limit, and the legacy list-returning `search()` API remain unchanged.
  CLI `count` remains returned count. False `has_more` is query-specific, not
  proof of exhaustive relevant-document coverage.
- In-memory default upgrade uses the SHA-256 of the exact command-normalized
  shipped template. Repository history confirms the original shipped template
  normalizes to the same fingerprint. Custom prose, including prompts merely
  containing the old five-word quotation language, is preserved rather than
  matched by the former broad substring heuristic. No load-time disk write.
- Current-case selection, closed corpus, source URI scheme, and title/subtitle
  composition are unchanged. New sessions after application-code reload receive
  the revised default. Existing sessions do not.

## Automated validation

Isolated tracked-source copy: `/tmp/oll-prior-quality-2mnJ5a`.
Existing `.venv` reused; all test configuration/archive/cache/library/state paths
pointed into the temporary tree. Final `uv run --no-sync python -m unittest
 discover -s tests`: **1011 tests passed** (43.291 s). Package and new harness
`py_compile` passed. `git diff --check` passed.

New tests cover overflow, exact limit, zero matches, empty/tokenless queries,
upper/lower clamps, match/sort legacy-list equivalence, full IDs/source links,
date provenance, CLI metadata and failure propagation, exact default upgrades
across legacy command prefixes, no configuration disk writes, preserved custom
prompts and model/reasoning profile, and prompt composition contracts. Existing
Prior Brief extraction-failure retention, missing-source, quote-target and app
composition tests remain passing. Behavioral tests are separate opt-in scripts,
not disguised unit tests.

## Six paired synthetic runs

Runner: `tests/run_prior_brief_acceptance.py`. Model held constant at the
configured Prior Brief profile: Fireworks
`accounts/fireworks/models/deepseek-v4p1-flash`, **high**. Twelve fresh runs,
one old/revised pair for each scenario; same system prompt, production CLI/search
implementation and 25-document synthetic corpus. Only the runtime Prior Brief
prompt differs. This is a prompt comparison, not a historical CLI benchmark.
Existing authenticated Pi runtime was used, with no web extension and only
`bash,read` tools. Command traces showed no web or CourtListener requests.
This harness is not an OS-level shell/network sandbox.

Corpus: directly relevant opening, respondent opposition, adult-only and
nondependent-only discussions, eight repetitive memos, twelve numeric-token
noise documents, and a recent derivative opening with fixed file-mtime fallback.
The opening has 240 background paragraphs followed by a material qualification.
The full body fits the tool output budget: this tests excerpt-vs-full reliance,
**not forced multi-chunk truncation recovery**. Fixtures explicitly label
synthetic advocacy, so attribution success here is not strong evidence of legal
calibration on real briefs. Repetitive short documents can outrank the long direct
brief; this is not a measured recall improvement on the private archive.

| Scenario | Searches old → revised | Seconds old → revised | Reported cost old → revised |
| --- | ---: | ---: | ---: |
| Direct match | 2 → 8 | 32.10 → 29.85 | $0.007110 → $0.007099 |
| Conflicting advocacy | 4 → 6 | 29.49 → 39.84 | $0.007681 → $0.007036 |
| Broad/noisy query | 7 → 18 | 59.39 → 38.68 | $0.010421 → $0.010216 |
| Late qualification | 4 → 4 | 25.65 → 19.37 | $0.005765 → $0.004685 |
| Missing companion | 6 → 9 | 27.03 → 23.44 | $0.005903 → $0.006338 |
| Recency/date fallback | 6 → 3 | 45.14 → 31.51 | $0.009403 → $0.005822 |

Search counts count `search-briefs` invocations, including multiple commands in
one bash call; startup reconnaissance and direct SQLite inspection are additional
work, not included in that metric. Median searches **5 → 7 (+40%)**, missing the
25% reduction target. The single direct-match pair also regressed (2 → 8).
Median latency **30.80 → 30.68 seconds**: no meaningful speedup demonstrated.
Total reported cost **$0.046283 → $0.041197**; total for all twelve **$0.087480**.
Summed reported input tokens **114,536 → 118,474**; output **26,702 → 19,767**
(cached-token usage is separate in raw events; these are not unique prompt-token
counts). One pair per scenario does not establish statistical performance gains.

### Observed revised-answer successes

- Direct opening ranked first for substantive queries; recent derivative ranked
  first for the explicit recency request.
- Material late qualification and adverse position were retained; substantive
  propositions were generally attributed to the briefs rather than current law.
- Adult and nondependent contexts were labeled separately; file-mtime fallback
  disclosed; missing reply generally described as not located in this snapshot.
- Source IDs in linked recommendations came from the synthetic index.

### Remaining failures (not waived)

- Direct answer linked seven companion memos not extracted and generalized their
  content. It disclosed sampling, but that does not meet the objective full-source
  inspection criterion. Missing-companion and late-qualification answers also
  discussed sources without complete extraction. None of the six revised runs
  used `read`; complete primary-brief JSON was often delivered directly by bash,
  which is stronger evidence than fetching to an unread file, but does not prove
  compliance with the prescribed chunk-to-EOF workflow for longer sources.
- Direct and conflict answers each included two quotations longer than ten words.
  There were also altered/misattributed short quotes: conflict attributed
  “does not address dependent-child inclusion” to the adult brief, though that
  exact phrase belongs to the nondependent brief. Some apostrophes were changed.
- Conflict began with `echo`/`ls` reconnaissance, attempted SQLite table discovery,
  then used Python SQLite inspection and sliced one extraction to 600 characters.
  Its remaining-document counts were wrong. These are not efficient CLI-only
  discovery or complete verification.
- Broad/noisy answer used 18 searches and asserted only one substantive document
  and no cross-context transfer anywhere in the snapshot without inspecting every
  document (the child query did return all 25 metadata rows). Recency also used
  stronger “only direct” coverage language than the query evidence warrants.
- Several link labels shortened indexed titles; repetitive memo discussion added
  noise instead of stopping after the material direct/contrary sources.

Raw local artifacts: `/tmp/oll-prior-paired-20260915/` (`metrics.json`, each run's
`events.jsonl`, `answer.md`, stderr, workspace and synthetic snapshot). These are
local evidence, not required runtime files. No private archive material was used.
The reusable runner now explicitly pins CLI imports to its isolated project via
`PYTHONPATH`; the recorded pairs reused the installed editable CLI implementation
with temporary data paths. Prompt and search behavior were identical between
that installed implementation and the staged candidate.

## GUI validation and limitation

`tests/preview_prior_brief_quality.py` created a separate non-unique application,
temporary settings/archive/library/cache/state, blocked Python socket connections,
and auto-closed. Native accessibility observation confirmed the saved synthetic
answer, title/subtitle and linked-title text in window 2346121833, PID 11206.
Existing user window/session was not navigated or modified.

Programmatic checks in that real GTK instance confirmed saved-answer readback,
Agent-panel source-title and exact short-quote targets, opening the indexed source
through the title target, and dispatching the quote target to its reader. These
are callback checks, **not physical link-click acceptance**.

The full saved-answer criterion is **not passed**: reopening a saved answer in
its main reader is distinct from rendering it in the Agent panel. Existing
`_apply_reader_markdown_spans` does not install prior-brief link targets, whereas
`_apply_agent_markdown_spans` does; saved-reader quote navigation was not proven.
This preexisting reader gap was not silently fixed under prompt/search scope.

## Follow-up boundary

Evaluate stronger enforcement separately: a source-read coverage ledger with
bounded full-text delivery, source-specific exact-quote validation before saving,
and a gap-driven discovery budget. Independently address saved-reader link/quote
parity and validate actual clicks in a synthetic instance. No such enforcement or
GUI behavior changes are claimed here. Keep the same model until those options
are evaluated; do not infer success from revised wording alone.

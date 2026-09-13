# General Law quality acceptance — 2026-09-13

## Disposition

**Retrieval regression checks pass; end-to-end quality/efficiency acceptance FAILS.**
Keep the model and saved reasoning/profile settings unchanged. The code fixes
remove reproduced unsafe acceptance and evidence-metadata defects. The skill
changes are implemented but remain provisional: these runs do not establish
consistent legal calibration or the requested 25% efficiency improvement.
Do not describe this work as a successful model benchmark or a speed upgrade.

All implementation is in OpenLawLens. No database/configuration/saved-answer
migration, authority cleanup, launcher change, Desktop_Files change, XREMAP
change, or model-profile change was made. Existing bad cached authorities and
the previously reviewed answer remain unchanged for user-directed handling.
New Agent sessions preload the changed skill; existing sessions do not.

## Implemented safeguards

- CCP aliases share parser/link patterns. Qualified citations are consumed
  completely; unsupported/conflicting prefixes cannot fall back to WIC.
- LegInfo titles are identity evidence, not body text. Extraction scopes the
  site's `single_law_section` container when present, excludes navigation,
  validates the heading/content and conflicting code/title identities, and
  raises `LegInfoError` before authority caching. HTTP/network failures and
  timeouts do not write an authority. No Probate support was added.
- Case windows contain entire selected matches before merging; query rounds
  prioritize first occurrences over seconds. Final source slices determine
  returned match metadata and counts. Query accounting separates absent text,
  oversized matches, match-count limits, passage-count limits, and total budgets.
- Pinpoint attribution requires a single consecutive ascending marker sequence
  consistent with the official citation and existing numeric range/tolerance.
  Mixed, descending, repeated, skipped, or out-of-range sequences conservatively
  suppress pages. Stored text/markers and opinion-level pagination stay unchanged.
  Match start/end pages are distinct from passage-start pages. No extra Scholar
  recovery is triggered by this output-only ambiguity decision.
- Lexical/semantic rows are locally court/publication checked. Exclusion counts,
  upstream-unverified totals, coverage warnings, and opt-in 1,200-character
  compact snippets are additive. No replacement page fetches occur.
- The skill alone owns the revised efficiency and legal-calibration instructions.
  Route A/B, the published-case floor, same-round extraction, direct extraction,
  closed-corpus workflows, and Subsequent Treatment ceilings remain intact.

## Deterministic and live source checks

Final isolated source validation: **1,008 unittest tests pass**, package and new
harness `py_compile` checks pass, the Agent Skill validator passes, and
`git diff --check` passes. Existing SQLite
startup, Route A/B, parallelism, direct extraction, official-copy reconciliation
and recovery, closed-corpus, and Subsequent Treatment tests ran in that suite.

New `tests/test_general_law_quality.py` covers supported code identities/aliases,
bare sections, unknown/conflicting/malformed qualified citations, valid short
bodies and hyperlinks, navigation-only/empty/wrong/conflicting pages, timeout and
fetch/extraction failures with no cache write, CLI error JSON, overlapping
windows, query starvation, Unicode/whitespace and clipping boundaries, oversized
queries, deterministic randomized window accounting, clean/missing/mixed/descending
pagination, match-spanning pages, lexical/semantic scope and publication policy,
explicit overrides, upstream counts, and complete compact/default JSON.

An isolated live LegInfo smoke check returned usable bodies for CCP §§ 527 and
527.6, WIC § 213.5, and Family Code §§ 6300 and 6340. WIC § 527.6 and Family Code
§ 6330 both raised `LegInfoError` (no matching section body). These checks did not
write to the user's Research Cache or Library. They establish extraction behavior
for these responses, not the content or existence of every California section.

Validation source copy: `/tmp/oll-quality-UrrX8P`; final test log:
`tests-final.log` within that copy. Commands from that isolated source tree used
the existing environment with synchronization disabled:

```sh
OPEN_LAW_LENS_CONFIG="$PWD/synthetic-config.json" \
OPEN_LAW_LENS_CACHE_DIR="$PWD/cache" \
OPEN_LAW_LENS_LIBRARY_DB="$PWD/library/test.sqlite3" \
uv run --no-sync python -m unittest discover -s tests
uv run --no-sync python -m py_compile open_law_lens/*.py
```

The temporary config was populated with a synthetic reader preference and an
empty temporary concordance path. An initial source-only extraction with no
concordance configured exposed an existing `None.open()` path in
`load_concordance_case_suggestions`; the fixture supplied its own empty
concordance instead of changing private settings or expanding this patch into
that unrelated defect.

## Six-run public-fixture model comparison

Baseline source: `a2f0a55a0c8201153816586587042a297d20a8ca`.
Candidate: the implementation's passage/search/parser/skill snapshot before the
final extra timeout/unsupported-response-code/named-heading regressions. Those
last narrow statute guards were checked separately; subsequent skill/passage
edits were formatting-only, with no substantive workflow or selection tuning.

Exact model: `fireworks/accounts/fireworks/models/deepseek-v4p1-flash`, `high`.
Authorized catalog discovery and a tiny live access probe succeeded; no model
substitution or saved-profile update occurred. Three baseline runs followed by
three candidate runs completed, each within a 300-second timeout. Total reported
model cost, including the access probe: **$0.107965714**, below the $1 budget.
The harness validates the catalog cost/maxima and stops at $0.50 completed
cumulative usage, reserving the conservative maximum next request ($0.47344)
under the cumulative cap. These are configured/provider-reported model costs,
not an independently reconciled invoice.

Public hypothetical: in an existing juvenile dependency proceeding, an applicant
seeks a long-term WIC § 213.5 order against a represented parent; application
and hearing notice were mailed to counsel, not personally served on the parent.
Ask for the best personal-service argument, contrary law, and the distinction
between the application and an issued order. No private trace, question, case
facts, documents, saved answer, or current-case export was provided to the model.

Public opinions were independently obtained with CourtListener into disposable
storage, not copied from the user's Library. The existing CourtListener API
credential was read only in-process to make those requests; no config or token
was copied to the test corpus or model context. Primary fixture opinions:

- In re Jonathan V. (2018) 19 Cal.App.5th 236, cluster 6239336.
- Searles v. Archangel (2021) 60 Cal.App.5th 43, cluster 4850176.
- Yu v. Pozniak-Rice (July 21, 2025, B337415), cluster 10637976;
  no official citation in the retrieved cluster metadata.

The search fixture offers those published California leads plus two explicitly
synthetic Oklahoma/Illinois exclusion controls. Queries return the same fixed
lead page; this is a controlled corpus, not a realistic relevance benchmark.
The fixture also supplies the five successful LegInfo bodies above and the two
navigation-only negatives. Other enactments/rule 5.630 were unavailable in this
fixture, a material coverage limitation. Other unrelated public cases acquired
during fixture identity investigation were in temporary storage but were not
search leads. Initial Justia/FindLaw downloads returned HTTP 403, and a Midpage
request returned HTTP 429; CourtListener resolved the needed fixture acquisition.

Production CLI argument parsing, statute extraction, cache/library lookup,
authority resolution, passage construction, row normalization/filtering and JSON
serialization were exercised. The acceptance-only adapter replaces external I/O:
fixed search/LegInfo responses, blocked additional network, and a typed no-further-
copy Scholar outcome. It does not fabricate official pagination. Baseline and
candidate used identical public fixtures, synthetic populated config, isolated
cache/library, SYSTEM plus the respective skill, and the unchanged General Law
template. The model had only `bash`; this is not the full production web-tool
or desktop environment. Public leads were named in the same fixture notice for
both variants, so the comparison is not blind discovery.

### Observed measurements

| Run | Tool-result chars | Generated tokens | Bash calls | Searches | Research rounds | Seconds | Model cost |
|---|---:|---:|---:|---:|---:|---:|---:|
| Baseline 1 | 142,166 | 12,325 | 25 | 4 | 11 | 174.50 | $0.020679 |
| Baseline 2 | 122,064 | 7,950 | 19 | 2 | 7 | 153.05 | $0.014736 |
| Baseline 3 | 127,988 | 14,885 | 23 | 5 | 9 | 214.04 | $0.021164 |
| Candidate 1 | 132,144 | 13,527 | 20 | 3 | 7 | 194.42 | $0.019757 |
| Candidate 2 | 125,043 | 9,031 | 21 | 3 | 5 | 133.82 | $0.015760 |
| Candidate 3 | 92,659 | 10,135 | 21 | 2 | 9 | 143.89 | $0.015839 |

Generated tokens are provider-reported output (including reasoning), not just
answer words. A research round is an assistant message containing tool calls;
one bash call may run multiple CLI commands. Search counts were verified by an
offline replay with pre-shell CLI instrumentation; the initial metrics logger
counted command-string occurrences and undercounted Baseline 3's shell loop as
three searches rather than five. The checked table corrects that count.

Median characters: **127,988 → 125,043 (2.3% reduction)**. Median generated tokens:
**12,325 → 10,135 (17.8% reduction)**. Both fail the 25% target. Candidate 3's lower
output volume includes prohibited clipping, so it is not a clean efficiency gain.
Median latency was 174.50 → 143.89 seconds in this fixture environment; no product
speed or isolated provider-compute improvement is claimed. Sequential ordering,
cache effects, tiny sample size, fixed leads, and missing rule/other statute
fixtures limit generalization.

### Evidence-output and legal-support audit

Pre-shell offline replay of the recorded commands exposed baseline out-of-passage
match counts **8 / 3 / 3** and out-of-scope lead counts **8 / 4 / 10**. Candidate
counts were **0 / 0 / 0** for both defects. No replayed authority falsely succeeded
on navigation text; the two specific negative statute paths are additionally
covered by direct deterministic/live checks. Replay checks raw production JSON
before the model's shell pipelines and is not additional paid model acceptance.
It does not reconstruct evidence that a model actually saw after clipping.

Candidate 1 and 2 kept complete JSON and used compact searches. Candidate 3 used
`head`/`tail` in 15 bash calls and also selected arbitrary text slices. The
no-clipping instruction was therefore **not reliably followed**. Some candidate
searches remained confirmatory and some passage retries remained repetitive.

All six final answers were reviewed against the critical support criteria:

- Candidates acknowledge that § 213.5 does not expressly demand personal service
  of the initial application, but still sometimes treat service "on the opposing
  party" as excluding service on counsel. This leaves the required-notice →
  mandatory-personal-service bridge unsupported or internally inconsistent.
- Candidate 1 and 2 distinguish same-day oral notice from mailed papers but do
  not adequately confront Jonathan V.'s actual mail/counsel discussion.
  Candidate 3 mentions the local counsel-service rule but does not squarely
  explain its mail-service implication.
- CCP § 527 qualifications are inconsistent: Candidates 1 and 3 mention the
  Family Code exclusion; Candidate 1 also limits the ex parte incorporation
  inference. Candidate 2 omits material qualifications. The conditional setting
  of § 527(d)(2) is not consistently preserved.
- Candidate 2 clearly explains Searles/Yu's intervening amendment; Candidate 3
  acknowledges it. Candidate 1 gives current exceptions but less clearly explains
  the legislative response. The amendment check is not uniformly strong.
- Candidate 1 expressly declines to treat § 6300 as importing the neighboring
  Family Code scheme. Candidate 2 does not assert that bridge. Candidate 3 still
  presents the § 6340 exception as part of the § 6300 route without verifying it.
- Candidate 3 supplies Jonathan V./Searles pinpoints despite ambiguous or absent
  source pagination, including an indirectly quoted Searles pinpoint. Suppressing
  tool pinpoints alone did not prevent the model from supplying its own.
- Candidates 2 and 3 use overconfident subtitles/titles. The body contains caveats
  but does not cure the stronger opening assertions. No consistent material-
  quality improvement over the baseline is established.

**Critical legal-support acceptance: FAIL.** No predetermined legal conclusion
was required. The problem is support, qualification, and reliable workflow
adherence, not whether the model advocated the requested side.

Artifacts remain machine-local at `/tmp/oll-quality-model`: six event streams,
answers, original `metrics.json`, tool-output audits, replay output, and
`replay-audit-summary.json`. Those contain only public/synthetic acceptance data.
No private trace or user research was uploaded or committed.

Opt-in harnesses: `tests/run_general_law_acceptance.py` and
`tests/general_law_fixture_io.py`. Stage baseline/candidate source snapshots and
public-only fixture data in temporary locations before running; never substitute
a real cache/library. The runner refuses changed model/budget assumptions and
never changes setup on failure. Normal unittest discovery does not run paid tests.

## Synthetic embedded GUI acceptance

`tests/preview_general_law_quality.py` starts a non-unique synthetic application
with populated temporary config, isolated cache/library/prior-briefs, no current-
case discovery, blocked network, and fake Pi/package files. It exercises the
production VTE wrapper, staging/preloading the skill once, session discovery,
final-answer polling, and the Markdown answer renderer. The second run passed
all checks; the initial harness omitted the required synthetic computer-use
package placeholder and correctly failed the wrapper's preflight. That harness
omission was repaired without changing production launch behavior.

Computer Use targeted synthetic PID 46281 and observed the rendered title,
subtitle, substantive answer, and selected Answer view. The synthetic window
closed on its own timer. No existing user window, document, saved research,
clipboard, or setting was manipulated. This validates launch/render mechanics,
not the quality of a live model answer.

## Remaining work and rollback

The 25% targets and all-critical-support gate remain unmet. Preserve these
measurements instead of treating a favorable individual run as acceptance.
Any follow-up should address the observed missing-premise and adverse-passage
failures and repeat controlled acceptance without relying on clipping for gains.
Keep model/reasoning and the mandatory case floor unchanged unless separately
approved. More complete public rule/statute fixtures would reduce the present
coverage confound.

Changes remain scoped source/prompt/tests/docs changes. If rollback is needed,
revert only those changes; never roll back user settings/data, remove cached
items automatically, or rewrite an existing answer.

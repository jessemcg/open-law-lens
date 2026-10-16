---
name: prior-briefs
description: App-selected closed-corpus Prior Briefs lookup and comparison workflow for embedded Open Law Lens sessions.
disable-model-invocation: true
---

# Prior Briefs

Answer only from the indexed prior brief archive snapshot and any current-case
factual context explicitly selected for this run. Do not browse the web,
research CourtListener, or treat prior advocacy as legal authority. Use the Open
Law Lens CLI iteratively to find candidate briefs, then inspect the full text of
every brief relied upon.

Use this command prefix directly, without startup reconnaissance:

```bash
"$OPEN_LAW_LENS_PROJECT_DIR/../UvEnvironments/project-env" run OpenLawLens open-law-lens <command>
```

## Select the requested scope

Choose the scope from the user's latest request: locating a document is not
researching or comparing arguments. A request to find a brief (including the
most recent brief making an argument) is a document lookup unless the user also
asks for analysis or comparison. Follow-ups may change the requested task within
the original session's corpus. Do not announce this classification or turn a
lookup into a research report.

## Document lookup

- Start immediately with `"$OPEN_LAW_LENS_PROJECT_DIR/../UvEnvironments/project-env" run OpenLawLens open-law-lens search-briefs "<short issue terms>" --match all --limit 5 --sort newest`
  for a recency request. No directory listings, environment inspection,
  database-schema reconnaissance, or direct SQLite queries; use the documented CLI.
- Match the substance of the argument, not the user's exact wording, unless
  the user expressly requests an exact phrase. A changed heading or
  standard-of-review formulation does not by itself make the argument different.
  Use short issue terms broad enough to retrieve alternative formulations, not
  the entire requested sentence. Distinguish genuinely different duties or
  issues (for example initial inquiry versus further inquiry).
- Review candidate metadata/snippets newest-first, then fully inspect the newest
  plausible match using the extraction rules below. Snippets locate candidates
  but do not verify them. Resolve plausible newer candidates before selecting
  an older one; do not read older supporting briefs once the newest match is verified.
- Normally use one search, with at most one or two targeted refinements for a
  concrete gap: no relevant hit, a plausible newer candidate, a date ambiguity,
  or an unresolved substantive distinction. A restrictive exact-phrase hit alone
  does not establish substantive recency; broaden once if needed. Expand beyond
  this only to resolve an identified uncertainty that could change the selected
  document, never to collect examples or repeatedly confirm the same result.
  Do not inspect SQL to seek exhaustive certainty.
- Stop when the requested document is verified and no plausible newer candidate
  in the retrieved results remains unresolved. `has_more` alone does not justify
  reading older matches after a verified newest match; it also does not establish
  archive-wide completeness. If uncertainty remains, state it briefly rather
  than claiming a definitive latest filing.
- Return one linked title, document type/date, and one or two sentences explaining
  why it matches. Include at most one useful short exact quote. No ranked list,
  supporting or contrasting briefs, legal survey, joinders, or current-case
  comparison unless requested. If dates are tied or genuinely unresolved, give
  only the necessary alternatives and a brief explanation. State a file-date
  fallback when applicable; do not present it as a verified filing date or prefer
  an older exact-wording match over a newer substantive match.
- Do not read or compare the selected current-case fact pattern merely because
  it was attached. Use it only when the user's request requires those facts to
  identify the document or expressly asks for comparison.

## Research or comparison

Start immediately with `"$OPEN_LAW_LENS_PROJECT_DIR/../UvEnvironments/project-env" run OpenLawLens open-law-lens search-briefs "<terms>" --match all --limit 5`, not
startup reconnaissance. Use short discriminating all searches or specific phrase
searches; default to 5–10 candidates. Reserve any for a few meaningful
alternatives: it ORs individual tokens, including split citation numbers (213.5
becomes 213 OR 5). Use --match phrase when adjacency matters. Use `--sort newest`
when recency matters.

After a strong hit, search only to fill an identified gap, inspect contrary
discussion, or find companion briefing. Stop when additional results merely
repeat the same proposition; broader user requests may justify continued
research. Preserve complete search JSON, full IDs, source links, document types,
and date provenance. Never clip JSON with head/tail, suppress extraction errors,
or replace complete metadata with shortened IDs. Search errors are errors, not
evidence of absence. The returned count is the number delivered; limit is the
effective bound and has_more indicates additional matches for that query.
has_more: false means all matches for that query were returned, NOT that every
relevant document was found.

## Source verification and answer rules (both scopes)

Fetch each selected brief once with:

```bash
"$OPEN_LAW_LENS_PROJECT_DIR/../UvEnvironments/project-env" run OpenLawLens open-law-lens extract-brief <brief_id> --output-dir "$OPEN_LAW_LENS_AGENT_WORKSPACE/brief-<brief_id>"
```

The absolute output directory must be new and inside the disposable agent
workspace. Fetch each selected document once; the CLI exports metadata.json,
manifest.json and ordered lossless part-0001.txt files, each at most 32 KiB UTF-8
and 1,500 lines. Read metadata and the manifest, then read EVERY part in manifest
order until EOF before relying on that brief. Concatenating all parts exactly
reproduces the source. Fetching is not reading; metadata or grep is navigation,
not full inspection. Chunk numbers are not legal pinpoints. Check late
qualifications and contrary passages before answering. If export fails, inspect
the structured error; never repeat extraction merely to work around clipped
JSON. If complete inspection cannot be finished, omit reliance or explicitly
disclose the inspection limitation. Temporary extraction files are authorized
inside the disposable agent workspace only.

Identify every discussed source with the exact Markdown link returned by search,
in this form: `[Exact indexed title](open-law-lens://prior-brief/<brief_id>)`.
Put that linked title close to the discussion and any quote from that brief.
When quoting, use only two to ten words (2–10), copied as exact continuous phrases
and each associated with its source link. A lookup does not require a quote;
research/comparison answers should include useful short quotes. Paraphrase longer
passages; never insert brackets, alter wording, or join separated fragments
inside an exact quotation.

For research or comparison only, lead with ranked document recommendations:
strongest directly relevant brief first, then genuinely useful supporting or
contrasting documents. For document lookups, the single-result answer rule above
takes precedence. Summarize arguments rather than writing an unqualified legal
opinion. Explicitly attribute propositions: the opening brief argues, the
respondent concedes, the brief cites. Identify contrary authority as reported by
the brief; do not declare which view currently controls or what a litigant must
show as independently verified law.

Keep dependent-child inclusion, adult protection, nondependent-person eligibility,
trial burden of proof, and appellate review distinct. Do not transfer standards
between these contexts without source support and qualification. Label weaker
contextual sources accurately, and do not count repetitive companion documents
as independent support.

State search limitations narrowly: the strongest match I found; I did not locate
a reply in this indexed snapshot. Do not turn no retrieved result into
archive-wide absence or claim exhaustive coverage.

Distinguish opening briefs, reply briefs, respondent's briefs, oppositions,
Phoenix H. memos, and other documents. For a request for the most recent document,
use the indexed document date and explain when it is a file-date fallback.

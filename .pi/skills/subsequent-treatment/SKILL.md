---
name: subsequent-treatment
description: App-selected bounded Subsequent Treatment workflow for embedded Open Law Lens sessions.
disable-model-invocation: true
---

# Subsequent Treatment

Analyze how subsequent published California cases treated the target case.
Discovery and extraction are hard-bounded: follow this fixed workflow exactly
and stop where directed. Use only the Open Law Lens commands supplied in the
request. Never use generic web search, Google Scholar,
California Courts pages, or alternate opinion sites, and never manually call
`extract-slip-opinion` or `lookup-citation`, to discover later cases or obtain
pagination, reporter metadata, links, or official copies. Never orchestrate
Scholar or any browser step yourself. No general web-search tool is available.

Apply the preloaded Legal Researcher's bounded execution rules to every supplied
command: bash tool `timeout: 180`, complete JSON stdout, separate stderr, saved
baselines, and short source phrases for passage matching (not semantic questions).
Temporary JSON may be saved only in the private workspace. Announce each
recovery's two-minute budget. After an unexplained abort or desktop-readiness
failure, suspend further Scholar attempts for this run, including other selected
cases; continue from verified baselines and disclose the actual failure, never
an invented no-display diagnosis. These rules do not expand discovery.

## Discovery ceiling

1. Run the supplied `published_citing_cases_command` exactly once.
2. If that command fails, returns no useful leads, or the cluster id is a local
   external id, run at most the two supplied non-paginated CourtListener searches
   and no others. First run `citation_search_command`, one exact official-citation
   phrase search.
3. Only if still needed, run `case_name_search_command`, one exact case-name search.

Do not retry network timeouts, paginate with `--next`, broaden or rewrite queries,
use semantic search, or invoke any web search. The only permitted retry is the
single retry of one command that fails with a transient SQLite `database is locked`
error; never replay a recovery/import outcome. If bounded discovery still yields
no usable leads, stop and report that subsequent-treatment coverage is limited or
unavailable; do not continue searching. This ceiling supersedes Legal Researcher's
general discovery allowance, without weakening verification or recovery limits.

Treat search results as leads only. Select the most significant published
subsequent California cases. Three to five cases is a ceiling and a preference,
not a quota: use fewer when only fewer can be verified, and disclose incomplete
CourtListener coverage. Never use unpublished cases as controlling treatment.

## Selected-case extraction

- Issue `compact_extract_command` baseline extractions for independent selected
  cases in parallel in the same tool round.
- Inspect `official_pagination`, `source_url`, and `warnings` in each result.
- For each selected case still lacking official pagination, make exactly one
  sequential `recover_official_extract_command`, letting Open Law Lens perform
  its internal baseline and single Scholar attempt. Use the selected case's
  known official citation in that template. Only if no usable citation is known,
  replace the citation argument with `--cluster-id <cluster_id>`; choose one
  identity form, not two attempts. Skip recovery entirely for an already
  paginated Library reconciliation, even if its durable identifier differs from
  the requested cluster. Apply the shared execution-failure stop rule.
- If compact passages are inadequate for a relied-on case, perform at most one
  ordinary `full_extract_command` for it. Never run a second recovery attempt
  for the same case, including across identity aliases.

## Citation, fallback, and disclosure

A supplied pinpoint or a page quoted by another opinion is not independently
verified. Check query accounting and match-level pages; empty phrase matches or
ambiguous excerpt pagination never authorize another recovery. Rely on the best
citation returned by the bounded sources; do not delay the answer to hunt for an
official reporter citation they did not return. State plainly when a citation
remains uncertain.

If a recovery returns no qualifying copy, is blocked, times out, or fails
validation, immediately rely on the best unpaginated baseline Open Law Lens
returned, disclose the missing official pagination, and link the case name or
citation to the `source_url` that extraction returned. When no source URL was
returned, say so; do not search elsewhere for one.

For each selected subsequent case, explain how it used the target case: agreed
with it, distinguished it, limited it, extended it to a different fact pattern,
criticized it, or used it in another identifiable way. Omit any treatment
characterization the extracted text does not support rather than inferring one.
If a citation lead exists but no bounded source produced verifiable text, omit
that case and disclose the gap. Keep the answer concise. Use normal legal prose
for case names and citations; reserve backticks for CLI commands, file paths,
and other literal technical text.

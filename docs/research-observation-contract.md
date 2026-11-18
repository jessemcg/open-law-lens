# Passive research command observations (v1)

Open Law Lens can provide a separate content-free receipt for a research CLI
invocation made within a registered app-owned Pi run. The enclosing app/workflow
owns the run even when it calls Open Law Lens across projects. The receipt is
not joined to a particular Bash tool call and is not part of CLI stdout/stderr,
exit handling, or the model's tool results. No desktop reader/GUI HTTP activity
is collected. Standalone installs, manual CLI use, an old/missing collector,
missing/unsafe runtime storage and disabled metrics need no sibling project and
silently continue without receipts.

## Transport and bounds

`open_law_lens/research_observation.py` uses only the standard library. It opens
an existing private context for its own `PI_SESSION_ID`, reading just the run
UUID from `PI_RUN_METRICS_SUBPROCESS_V1_<session-id>`. An existing owned 0700
`$XDG_RUNTIME_DIR/pi-run-metrics-v1-<uuid>` and no symlink traversal are required.
No archive root or arbitrary output path is read from the caller. The producer
exclusively claims a 0600 single-link numbered slot (001–128), writes one JSON
start line, and writes one bounded completion line on the same descriptor. The
empty `saturated` marker records exhaustion. Total budget is 8 KiB per slot,
40 logical requests with up to three attempts each, 16 search pages. A capped
receipt keeps a bounded prefix, not invented totals. No network, log output,
background process, sleep, authorization, configuration write, or retry is
added by collection. Late receipts cannot enter a subsequent run.

## Allowed content only

- Start: `version: 1` and a fixed command name: `case-search`, `lookup-citation`,
  `extract`, `extract-case`, `extract-slip-opinion`, `extract-statute`,
  `extract-rule`, `lookup-statute`, `lookup-rule`, `published-citing-cases`,
  `recover-scholar`, `search-briefs`, `extract-brief`. Help/parse failures, app
  launch/open, maintenance and storage administration are outside dispatch.
- Completion: version, monotonic elapsed milliseconds, validated numeric exit
  code or null if dispatch did not return, `capped`, `requests`, `pages`,
  `sources`, and `yield`. A command-specific `ContextVar` shares the accumulator
  across all clients in the invocation without global active-command state.
- Logical request: fixed family (`search`, `citation_lookup`, `cited_by`,
  `cluster`, `opinion`), GET/POST, and `ok`, `http_error`, `transport`, `decode`,
  `shape`, or `incomplete`. These describe the verified CourtListener HTTPS v4
  request position, not billing, redirects/wire attempts, or an inferred call
  from the CLI name. Each actual application `urlopen` attempt records nullable
  status 100–599, fixed outcome (without logical `shape`), elapsed milliseconds,
  retry code (`throttle`, `gateway`, or null), and observed backoff milliseconds.
  HTTP 200 may still be decode or application-shape failure.
- `sources`: counts by `lookup_library`, `lookup_cache`, `resource_library`,
  `resource_cache`, `opinion_library`, `durable_case_library`, `refresh_lookup`,
  `refresh_resource`, `unverified_request`. These observe existing branch
  decisions, not changes to filtering, cache use or retries. Scholar, LegInfo,
  California rules/slip-opinion retrieval, Gmail and general web requests are
  **not** CourtListener traffic. An unverified next/resource URL records only
  a coverage gap; no URL content is stored.
- Search page: lexical/semantic/unknown, first/next, rows received/delivered,
  and counts by `missing_identity`, `unverified_court`, `court_out_of_scope`,
  `unverified_or_unpublished_status`, `delivery_limit`. Cursor mode can be
  unknown. Upstream advertised totals are not a measure of delivered leads.
- Typed `yield`: `clusters`, `lookup_text_requested`, `lookup_text`,
  `citing_cases`, `briefs`, `authority_type`, `baseline_text`,
  `baseline_pagination`, `text_available`, `text_delivered`,
  `official_pagination`, `passages`, `matches`, `unmatched_queries`,
  `omitted_matches`, `exported`, `recovery`. Optional keys are present only
  where measured. `recovery` is an allowlisted outcome (`not_needed`,
  `no_target`, `recovered`, `blocked`, `rejected`, `failed`, `not-found`,
  `cancelled`, `busy`, `saved-but-unverified`, `unknown`), separate from
  usable baseline text. Passage counts use the already-built response, without
  a second search, query, recovery attempt, or stdout parsing.

Arguments, requests, citations, cluster/opinion IDs, filenames, paths, URLs,
credentials, snippets, opinions, command output, and exception text never enter
a receipt. No source/cache/settings data is changed by instrumentation.
PiRunMetrics has a corresponding fixed schema and validates independently
before folding detail into the existing finished line. Missing or incomplete
receipts are unobserved, not proof of no work. See its `docs/workflow-activity.md`
for cohort reporting, coverage, and rollout. Set `PI_RUN_METRICS_ENABLED=0`
to disable; no reinstall, schema migration, archive reset or backfill is needed.

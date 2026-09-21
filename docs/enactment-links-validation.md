# California enactment links — validation (2026-09-20)

## Scope and implementation

All 29 LegInfo codes share `california_codes.py` (CSM § 2:8 labels, including
`Cal. U. Com. Code`, plus compatibility aliases). `CitationContext` and the pure
`collect_authority_links` collector separate automatic inference from the personal
bare-lookup preference. Lists resolve written members/endpoints only. Offsets are
rendered Unicode character offsets; case preparation scopes context per opinion.
Original declaration text is retained in context when Markdown or direct-quote
formatting removes delimiters, preventing quoted declarations from becoming
unquoted defaults. Juvenile Rule membership is an explicit active Division 3
snapshot, not a Title Five numeric-range guess.

Case batches and shared reader workers dispatch typed case/statute/rule tags.
Both final-answer paths use the collector, retain case-mode restrictions, preserve
quote/title/external navigation, and clear typed maps. Reader generations discard
obsolete preparation and lookup callbacks, including before enactment cache
insertion. Cache generations independently protect cache clearing. Official
fetches are bounded to 4 MiB, validate substantive identity, and handle timeouts.
No durable case persistence service is used for enactments.

## Automated checks

An isolated tracked-source copy at `/tmp/oll-enactment-validation` was used with
temporary runtime state and the existing Python environment (no dependency
changes). The two pre-existing untracked production files were not copied or
modified.

- `uv run python -m unittest discover -s tests`: **1,072 passed**.
- `uv run python -m py_compile open_law_lens/*.py`: passed.
- `git diff --check`: passed in the source repository; new files checked too.
- Catalogue tests iterate all names, CSM abbreviations, supported aliases,
  uppercase/canonical IDs, qualifiers, and URLs.
- Exact span/target tests cover lists/ranges, reverse forms, subdivisions,
  three-component rules, Unicode, and single-line wrapping.
- Negative tests cover malformed and historical numbers; foreign, federal,
  local, constitutional/regulatory/treatise references; quoted/conflicting
  declarations; same-paragraph constraints; separate-opinion isolation; and
  non-California case metadata.
- Shared reader/case/live-answer target parity, nested emphasis, quote offsets,
  page markers, existing case links, and all answer modes pass.
- A deliberately blocked worker leaves the GLib heartbeat running; an
  800-link shared document crosses multiple 250-tag batches. Superseded work
  cannot tag replacement content. Lookup callbacks are rejected before publish.
- Wrong/missing bodies, navigation/search pages, wrong alphanumeric identities,
  timeouts, and unrelated rule redirects fail before cache writes. Paragraphs
  beginning with another rule's citation remain content, not truncation markers.
- Client tests verify transient enactment caching and an unchanged durable
  library. Existing resolver, agent, cache, Research Set, and full regression
  tests pass.

## Desktop acceptance

Ran `tests/preview_enactment_links.py` from the isolated copy via Linux Computer
Use, under `com.mcglaw.OpenLawLens.EnactmentPreview`, with fresh temporary config,
cache, prior-brief database, and durable library. No production data was used.

Observed:

- Identical case and saved-answer fixture: **10 statutory links, 3 rule links**;
  zero cached enactments before clicking. Explicit negative examples unlinked.
- Government Code § 815.6, plural Probate Code endpoint § 102, Health and Safety
  Code § 1200, and rule 5.112.1 clicked through the normal typed handlers.
- Rule 5.112.1's cross-reference opened rule 5.111. Rule 5.502's WIC list member
  opened § 361.5. Opened statutes displayed owning-code cross-reference links.
- A synthetic opinion without a code declaration left §§ 300 and 361.5 unlinked;
  the same references linked under the WIC declaration.
- Current-official-text metadata appeared in the original acceptance run; the
  follow-up below removes that extra notice as requested.
- Rapid navigation during a delayed lookup discarded the result before caching.
- Controlled source failure showed an honest error and inserted no authority.
- Returned to the original saved answer, selected text, and verified ordinary
  clipboard copy contained the synthetic fixture (522 characters).
- Final temporary Research Cache: four statutes and three rules; durable
  `opinions` table: **zero rows**. The synthetic process was stopped.

Desktop validation also exposed unescaped ampersands in ordinary status toasts;
toast titles now escape markup. This does not alter citation text or saved data.

## Independent official-source checks

Separate from network-free unit tests, the final extraction code validated:

- [Government Code § 815.6](https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=GOV&sectionNum=815.6): matching body, 399 characters.
- [Rule 5.112.1](https://courts.ca.gov/cms/rules/index/five/rule5_112_1): matching heading and body, 766 characters.

Also inspected [rule 5.502(36)](https://courts.ca.gov/cms/rules/index/five/rule5_502)
and the [Title Five division listing](https://courts.ca.gov/cms/rules/index/five)
for WIC provenance/membership, and [CSM § 2:8](https://sdap.org/wp-content/uploads/downloads/Style-Manual.pdf)
for code abbreviations. Successful HTTP status alone was not treated as validation.

## Follow-up: headers, unidentified sections, and Smit spacing

- Removed the current-official-text notice, retaining section/rule numbers.
- Removed the parser's WIC fallback and retired the bare-number code preference
  from the UI. Legacy config fields round-trip inertly; no private config was
  modified. Unqualified number/section lookup inputs ask for the code. Explicit
  document context still qualifies otherwise-bare references; unidentified codes
  never gain links.
- Read-only inspection of public *People v. Smit*, opinion 6106649, confirmed
  CourtListener HTML literally contains `( <em>People v. Smit</em>` and
  `( Health &amp; Saf. Code`. Display-only normalization removes inline padding
  after `(`, remapping page/style anchors before citation scanning. Original
  opinion JSON remains untouched. All 12 Smit page markers validated afterward.
- **1,076 tests passed** in the isolated copy; package compilation and whitespace
  checks passed. Added HTML, existing-display, multi-opinion, Unicode-offset,
  idempotence, and ambiguous-input regression coverage.
- Linux desktop checks in the isolated preview verified tight opening-parenthesis
  spacing, the header `Government Code` / `§ 815.6` without the notice (F4), and
  unlinked unidentified sections beside a linked explicitly named code (F7).
  No network fetches were needed; the production window was left untouched.

## Limits and compatibility

This is conservative common-citation recognition, not a measured recall claim
or exhaustive shorthand resolver. Ambiguous references remain plain text;
year-shaped inherited list members are deliberately conservative. Local/federal
rules, regulations, constitutions, session laws, historical versions, and old
rule-number conversion are outside scope. No schema, launcher, CLI, settings,
cache-rebuild, or stored-text migration is required. Restart and reopen content.

---
name: legal-researcher
description: Research and verify California legal authorities through Open Law Lens, including published-case discovery, statutes, rules, subsequent treatment, official reporter citations, quotations, holdings, and pinpoint citations. Use for California Law, Subsequent Treatment, and Appeal Issue research.
---

# Legal Researcher

Use Open Law Lens as the primary research and verification system. Treat search
results, snippets, and web pages as leads, not authority.

## Command prefix

Run commands from any workspace with:

```bash
uv run --project "$OPEN_LAW_LENS_PROJECT_DIR" --no-sync open-law-lens <command>
```

The embedded launcher uses an already synchronized environment, so retain
`--no-sync` in agent commands.

## Research workflow

1. Identify the jurisdiction, issue, procedural posture, and requested output.
   Classify what principally controls the question: a statute, a rule, a known
   case, or an unresolved case-law issue.

### Route gate

Before extracting, route the question through exactly one of two routes.
Never classify a question down into the enactment-only route merely to avoid
case research.

**Route A — narrow enactment-only exception.** Use only when the user
*expressly* asks for current statutory or rule text, a citation, an effective
or operative date, or another mechanical fact that is fully stated in the
enactment itself, and the answer stays confined to that text. Do not define a
legal status, doctrine, test, standard, or term of art inside this route.

**Route B — mandatory enactment-plus-case route.** Use for every definition
or explanation of a legal status, doctrine, test, standard, or term of art,
and whenever the answer addresses scope, application, biology, neighboring
classifications, burdens, rebuttal, conflicts, exceptions, rights, duties, or
practical consequences.

- "What is a presumed father / presumed parent?" is explicitly a
  mandatory-case (Route B) example, not a purely textual definition.
- A "simple what is" question controls answer *length* only; it never waives
  this source floor.
- Once a mandatory trigger applies, you must successfully extract and cite at
  least one leading published California case before giving a final answer.
- Do not silently decide that the statutes are "enough" while adding a
  proposition that is not apparent from those statutes.

2. In Route B, extract the current controlling enactment first:

   ```bash
   uv run --project "$OPEN_LAW_LENS_PROJECT_DIR" --no-sync open-law-lens extract-statute "<citation>"
   uv run --project "$OPEN_LAW_LENS_PROJECT_DIR" --no-sync open-law-lens extract-rule "<citation>"
   ```

   In Route A, the enactment above is the whole job; leave the answer confined
   to that text and do not add case research.

3. If a reliable official citation or case name is already known, treat it as
   a lead and extract it directly; do not run a confirmatory `case-search`
   first. Prefer a bounded `--find` passage for the specific proposition and
   run one leading case with one or two broad exact terms:

   ```bash
   uv run --project "$OPEN_LAW_LENS_PROJECT_DIR" --no-sync open-law-lens extract-case "<citation>" --find "<term>" --find "<term>"
   ```

   Use `extract-case --cluster-id <cluster_id>` when citation or name
   extraction is unavailable or fails. `extract-case` supplies the
   Library/CourtListener/slip baseline text. Check `official_pagination`,
   `pagination_marker_count`, and `warnings`; usable unpaginated text may still
   return `ok: true`. Use `--refresh` only when a fresh baseline refresh is
   needed.

4. Issue independent statute/rule and known-case extractions in the same tool
   round when both are needed. Do not sequence the case extraction only after
   the statutes finish. Use the compact `--find` passages for the case; do not
   load the full opinion unless those passages are missing or inadequate.

5. When discovery is genuinely needed—no reliable citation or case name is
   known—run exactly one focused search and extract the best published result;
   expand or paginate only if those leads are inadequate. Do not issue multiple
   broad searches unless the first results are inadequate. Restrict to the
   Supreme Court with `--court cal` only when specifically seeking its
   authority:

   ```bash
   uv run --project "$OPEN_LAW_LENS_PROJECT_DIR" --no-sync open-law-lens case-search "<query>" --limit 5
   ```

   Treat results as leads. Prefer published California Supreme Court and Court
   of Appeal decisions. Use unpublished decisions only for noncontrolling
   context when useful.

6. Stop after the current enactment and the minimum case authority needed to
   support the answer. Do not expand into secondary cases merely because a
   leading opinion cites them.

7. Verify each proposition, quotation, publication status, and pinpoint against
   extracted full text before using it. A case proposition must be supported by
   the case you directly extracted, not merely by a case named inside another
   opinion.

### Bounded recovery

If the mandatory case cannot be verified immediately, follow this sequence
before finalizing:

1. Known-case extraction fails or returns no useful passage: retry with
   broader exact terms or the full text of that one case.
2. Identity or citation remains unresolved: run one focused published-case
   search and extract the best lead.
3. No case can be verified: disclose the case-law verification gap and confine
   the answer to the extracted enactment. Never state the unsupported judicial
   proposition or silently present the answer as complete.

For subsequent-treatment work, begin with the supplied citing-cases command.
Recover with focused case searches using the target name, official citation,
and distinctive citation phrases. Describe only supported treatment, such as
followed, distinguished, limited, extended, or criticized.

## Web-search fallback

Use Pi's `web_search` only for open-ended, unresolved verification that is not
official-copy recovery, such as investigating delayed reporter metadata or a
conflicting identity record. Never use `web_search` to retrieve an official
reporter copy, to repeat the default-browser Scholar recovery, or as a fallback
opinion-discovery service. Tavily, direct HTTP Scholar, alternate opinion
sites, and generic web search are never acceptable sources for an official
copy.

Make narrow searches combining the exact case name, docket number, filed date,
and reporter series such as `Cal.5th` or `Cal.App.5th`. Search results remain
leads. After finding a likely official citation, retry `extract-case
"<official citation>"` and rely on its validated extracted text. State plainly
if the citation or text remains uncertain.

Do not characterize a holding, treatment, quotation, or pinpoint from a search
snippet alone.

## Official-copy recovery contract

`extract-case` supplies the Library/CourtListener/slip baseline text. It never
performs direct HTTP Scholar search or native Tavily discovery. The only
non-baseline source for an officially paginated reporter copy is one confined
attempt in the user's current default HTTPS browser (never a hardcoded browser,
app ID, executable, or profile), driven by the app's confined, safety-checked
recovery job.

Apply this source order and stop at the first point that resolves:

1. **CourtListener / Library.** A CourtListener opinion that already embeds
   qualifying `[*page]` reporter markers is the official copy.
2. **California Courts slip opinion.** For a recent published California case,
   the slip opinion is the next best baseline; it is not an official reporter
   copy but is usable with a disclosed pagination limitation.
3. **One default-browser Google Scholar attempt.** Only when a relied-on
   published case still lacks official pagination. The recovery job resolves
   the current default browser, opens Scholar, and imports a qualifying copy
   when one is found.
4. **Stop.** On no result, no qualifying reporter markers, a CAPTCHA, an
   inaccessible link, or any job failure, stop and rely on the best baseline
   (slip opinion first, otherwise formatted CourtListener text) with an
   explicit pagination limitation. Do not proceed to any other service.

Never fall through to Tavily, direct HTTP Scholar, an alternate opinion site,
or generic `web_search` to obtain an official copy. After a successful import,
rerun `extract-case` (or `extract-case --find "<term>"`) so the answer quotes
and cites the newly saved Library copy.

The recovery accepts either an exact California official reporter citation
(e.g. `11 Cal.5th 614`) or, for a recent slip that has no reporter citation
yet, an existing CourtListener cluster plus case-name/docket/date identity. A
CAPTCHA, robot check, login prompt, or missing exact-result action stops the
job immediately; never solve or interact with it, and never fall back to
coordinates, typing, scrolling, screenshots, or unrelated windows.

## Pre-answer legal-source audit

Before writing the final answer, audit the title, subtitle, and body against
the extracted sources:

- Confirm every mandatory-case (Route B) trigger has at least one successful
  case extraction and a corresponding normalized case citation present in the
  body. If not, do not finalize: complete the bounded-recovery sequence first.
- Confirm each case proposition maps to a case you directly extracted, not to a
  case only named inside another opinion.
- Reconcile opening clauses, cross-referenced chapters, subdivisions, counts,
  and exceptions against the currently extracted enactment. Do not report a
  subdivision count or scheme from memory.
- Preserve every material "except," "unless," "may," "must," and "only"; do
  not strengthen a qualified rule into an absolute one or drop a stated
  exception.
- Map every non-obvious legal proposition and practical consequence to an
  authority actually extracted during the session. Delete unsupported
  frequency, history, rights, and practical-consequence claims—including
  biology assertions such as "regardless of biology" or "nonbiological"
  consequences—or research them explicitly.
- An amendment note proves an effective date, not that an amendment changed
  terminology only. Do not say the substantive framework "is the same" without
  separately verifying that history.
- Compare older cases' quoted statutory language and subdivision numbering with
  the currently extracted enactment. Use current wording and cabin the older
  holding to the proposition and statutory arrangement it actually decided.
- Do not cite a case mentioned inside another opinion as though that case
  itself was directly extracted and verified.
- Prefer current gender-neutral statutory terminology while explaining any
  legacy label the user requested (for example, the "presumed father" label).
- Use quotation marks only around exact, continuous source text. Do not present
  a bracketed rewrite as a purported continuous quotation.
- Keep search snippets as leads only; never quote or characterize authority from
  a snippet.

## Answer requirements

- For Appeal Issue research, make the required H1 title issue-specific: name
  the specific appellate issue in no more than 10 words, such as
  `# Cal-ICWA Inquiry`. Do not use a generic H1 title such as `# Assessment` or
  `# Issue Assessment`.
- For Appeal Issue research, treat the supplied fact pattern as the complete
  factual record. Base the factual analysis only on that text. Do not speculate
  that unprovided facts or a more complete record could alter the assessment,
  and do not add a generic record-completeness caveat. Identify a concrete
  ambiguity, contradiction, or missing record citation only where it affects
  the analysis.
- Confine research to California state law unless the question requires federal
  law.
- Distinguish controlling authority, persuasive authority, and prior advocacy.
- Include normalized citations for authorities relied upon.
- For a simple "what is" question, provide a short definition, the statutory
  routes, and only the material caveats—normally about 350 to 650 words unless
  the user requests depth.
- Use concise legal prose and address contrary authority or material gaps in
  the available legal sources.
- Use quotation marks only for exact, continuous text verified in the source.
- Do not invent citations, pinpoints, holdings, or publication status.
- If the available sources do not answer the question, say so directly.

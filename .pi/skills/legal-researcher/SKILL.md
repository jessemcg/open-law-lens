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
2. Search for California cases with focused terms:

   ```bash
   uv run --project "$OPEN_LAW_LENS_PROJECT_DIR" --no-sync open-law-lens case-search "<query>"
   ```

3. Treat results as leads. Prefer published California Supreme Court and Court
   of Appeal decisions. Use unpublished decisions only for noncontrolling
   context when useful.
4. Extract every authority relied upon. Prefer a known official citation or case
   name so durable library text can be reused:

   ```bash
   uv run --project "$OPEN_LAW_LENS_PROJECT_DIR" --no-sync open-law-lens extract-case "<citation or case name>"
   ```

   Use `extract-case --cluster-id <cluster_id>` when citation or name extraction
   is unavailable or fails. `extract-case` already runs the complete official-copy
   cascade (Library/CourtListener, California Courts slip text, Scholar, then one
   cached native Tavily discovery pass). Check `official_pagination`,
   `pagination_marker_count`, and `warnings`; usable unpaginated text may still
   return `ok: true`. Use `--refresh` only when a fresh fallback retry is needed.
5. Extract relevant enactments rather than relying on snippets:

   ```bash
   uv run --project "$OPEN_LAW_LENS_PROJECT_DIR" --no-sync open-law-lens extract-statute "<citation>"
   uv run --project "$OPEN_LAW_LENS_PROJECT_DIR" --no-sync open-law-lens extract-rule "<citation>"
   ```

6. Verify each proposition, quotation, publication status, and pinpoint against
   extracted full text before using it.

For subsequent-treatment work, begin with the supplied citing-cases command.
Recover with focused case searches using the target name, official citation,
and distinctive citation phrases. Describe only supported treatment, such as
followed, distinguished, limited, extended, or criticized.

## Web-search fallback

Use Pi's `web_search` only after enhanced `extract-case` remains unresolved and
open-ended verification is genuinely needed. This is especially appropriate
for investigating delayed reporter metadata or conflicting identity records,
not for repeating the native official-copy resolver.

Make narrow searches combining the exact case name, docket number, filed date,
and reporter series such as `Cal.5th` or `Cal.App.5th`. Search results remain
leads. After finding a likely official citation, retry `extract-case
"<official citation>"` and rely on its validated extracted text. State plainly
if the citation or text remains uncertain.

Do not characterize a holding, treatment, quotation, or pinpoint from a search
snippet alone.

## Answer requirements

- For Appeal Issue research, begin the final answer with a concise level-two
  Markdown heading of no more than 10 words that names the specific appellate
  issue, such as `## Cal-ICWA Inquiry`. Do not use generic headings such as
  `## Assessment` or `## Issue Assessment`.
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
- Use concise legal prose and address contrary authority or material gaps in
  the available legal sources.
- Use quotation marks only for exact, continuous text verified in the source.
- Do not invent citations, pinpoints, holdings, or publication status.
- If the available sources do not answer the question, say so directly.

---
name: legal-researcher
description: Research and verify California legal authorities through Open Law Lens, including published-case discovery, statutes, rules, subsequent treatment, official reporter citations, quotations, holdings, and pinpoint citations. Use for California Law, Helper Case, Subsequent Treatment, and Appeal Issue research.
---

# Legal Researcher

Use Open Law Lens as the primary research and verification system. Treat search
results, snippets, and web pages as leads, not authority.

## Command prefix

Run commands from any workspace with:

```bash
uv run --project "$OPEN_LAW_LENS_PROJECT_DIR" open-law-lens <command>
```

Use `--no-sync` when the environment is already synchronized.

## Research workflow

1. Identify the jurisdiction, issue, procedural posture, and requested output.
2. Search for California cases with focused terms:

   ```bash
   uv run --project "$OPEN_LAW_LENS_PROJECT_DIR" open-law-lens case-search "<query>"
   ```

3. Treat results as leads. Prefer published California Supreme Court and Court
   of Appeal decisions. Use unpublished decisions only for noncontrolling
   context when useful.
4. Extract every authority relied upon. Prefer a known official citation or case
   name so durable library text can be reused:

   ```bash
   uv run --project "$OPEN_LAW_LENS_PROJECT_DIR" open-law-lens extract-case "<citation or case name>"
   ```

   Use `extract-case --cluster-id <cluster_id>` when citation or name extraction
   is unavailable or fails.
5. Extract relevant enactments rather than relying on snippets:

   ```bash
   uv run --project "$OPEN_LAW_LENS_PROJECT_DIR" open-law-lens extract-statute "<citation>"
   uv run --project "$OPEN_LAW_LENS_PROJECT_DIR" open-law-lens extract-rule "<citation>"
   ```

6. Verify each proposition, quotation, publication status, and pinpoint against
   extracted full text before using it.

For subsequent-treatment work, begin with the supplied citing-cases command.
Recover with focused case searches using the target name, official citation,
and distinctive citation phrases. Describe only supported treatment, such as
followed, distinguished, limited, extended, or criticized.

## Web-search fallback

Use Pi's `web_search` only when Open Law Lens or CourtListener lacks or appears
to misstate an official reporter citation or official opinion text. This is
especially appropriate for a recent published California slip opinion with a
placeholder citation, only a docket number, or delayed reporter metadata.

Make narrow searches combining the exact case name, docket number, filed date,
and reporter series such as `Cal.5th` or `Cal.App.5th`. Prefer official
California court sources and trustworthy citation records. Search results are
still only leads. After finding a likely official citation, retry
`extract-case "<official citation>"` and rely on verified extracted text where
available. State plainly if the citation or text remains uncertain.

Do not characterize a holding, treatment, quotation, or pinpoint from a search
snippet alone.

## Answer requirements

- Confine research to California state law unless the question requires federal
  law.
- Distinguish controlling authority, persuasive authority, and prior advocacy.
- Include normalized citations for authorities relied upon.
- Use concise legal prose and address contrary authority or material gaps.
- Use quotation marks only for exact, continuous text verified in the source.
- Do not invent citations, pinpoints, holdings, or publication status.
- If the available sources do not answer the question, say so directly.

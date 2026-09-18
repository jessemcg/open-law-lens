# Research execution review — 2026-09-18

Follow-up to the Current Case TUI brief-prep trace review. The separate browser
stdio-inheritance and citation-as-case-title fixes remain in Open Law Lens;
this review propagates applicable instruction/command improvements without
changing tool permissions or legal-source requirements.

## Reviewed paths and decisions

| Path | Changes / boundary |
| --- | --- |
| Open Law Lens Law and Appeal Issue | Preloaded legal-researcher skill now specifies per-call bash timeout 180, sequential recovery timeout 120 plus progress, complete JSON/separate stderr, preserved baselines, one attempt across authority aliases, truthful error reporting, and suspension of further Scholar attempts on unexplained abort/readiness failure. Mandatory enactment-plus-case routing remains intact. |
| Open Law Lens Subsequent Treatment | Same execution rules; retains one graph command, two exact searches maximum, three-to-five verified-case ceiling, no web fallback. Generated searches request compact output; recovery template prefers the official citation with cluster-ID replacement only when no citation is known. |
| Open Law Lens system prompt | Removed obsolete permission for agent-driven desktop/browser recovery. Explicitly permits only private temporary research JSON in research-capable modes. Closed-corpus modes remain closed. |
| Open Law Lens command catalog | Recovery example includes timeout/progress and describes phrase matching and stderr separation. |
| Prose Proof Document citation stage (separate repository) | Same bounded execution/evidence rules, direct extraction before up to two focused identity searches, per-authority reuse, phrase-match accounting, match-level pinpoints, no unsupported corrections. Review still covers every supplied block; gaps go in terminal summary, not fabricated replacement text or new JSON fields. |
| Prose general questions / selected-text lookup | These are web-only, **not** Open Law Lens clients. Added bounded failed-query follow-up, passage inspection, accurate access-failure reporting, and legal-source/pinpoint caveats. No shell, local files, browser tools, or Open Law Lens access added. |
| Prose drafting, organize/refine, other proof stages | Deliberately unchanged: document/record-only work, not legal authority research. Citation stage alone gets the narrow documented CLI/temporary-JSON allowance. |
| Open Law Lens Research Cache and Prior Briefs | No research workflow added. Existing closed-corpus and prior-advocacy distinctions remain intact. |

`--find` uses normalized source phrases, not semantic questions. Empty matches
require saved-source review or a bounded shorter-phrase extraction, not a claim
that a proposition is absent. A document's supplied pinpoint is evidence to
check, never independently verified merely because source recovery failed.

## Configuration and deployment

No runtime configuration or case documents were edited. Existing custom prompts
and model profiles are preserved. The exact immediately preceding shipped
Subsequent Treatment default is recognized by SHA256 and upgraded **in memory**
using the existing config-load mechanism; the settings file is not rewritten.
Regression coverage verifies both non-writing behavior and custom preservation.

Fresh workflows load the revised skills/system prompts. Restart Open Law Lens
for the changed generated commands/default template; restarting both apps before
starting new work is the simplest handoff. Public CLI signatures, application
IDs, launchers and keyboard mappings are unchanged. No Desktop_Files or XREMAP
edits/deployment are required. Keep changes separate in the two repositories.

## Validation

- Open Law Lens: full suite **1,042 tests passed**, syntax compilation and
  whitespace checks passed. Includes generated-command tests, launcher resource
  isolation, mandatory-route contracts, failure rules, command catalog, and
  exact-default/custom-prompt preservation.
- Prose: full suite **549 tests passed**, package/window/test syntax compilation
  and whitespace checks passed. Includes resource staging, exact research tool
  allowlists, citation-only research boundary, scoped proof output contracts,
  and new instruction assertions.
- Both modified skills passed the skill validator.
- The preceding fix was already live-tested against Scholar with isolated
  cache/library copies. This follow-up did **not** run paid model acceptance,
  real-document proofreading, or another live browser recovery. Tests validate
  code/staging and prompt contracts, not guaranteed model compliance with every
  instruction. The 180-second per-call deadline is an agent instruction to set
  the bash tool timeout, not a new host-enforced overall session limit.

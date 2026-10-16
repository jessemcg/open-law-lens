# App-owned workflows and Focus-style Settings

Implementation/acceptance: 2026-10-16, Home computer only (RTX 3090; no GPU work
or model/network research required). Starting revision `8b12908`, clean tree.
Changes are confined to OpenLawLens. Focus was read as a design reference only;
no Focus imports or changes, dependency/lock changes, Desktop_Files/XREMAP edits,
production provisioning, settings migration, answer regeneration, or paid runs.

## Ownership and deterministic assembly

Each new embedded launch validates a mode/workflow pair and fixed readable,
nonempty resources before Pi execution. An explicit profile key wins; absent
keys retain the legacy mode-derived defaults. General mode is not a workflow:
Law and Subsequent Treatment have different skills and metrics tags.

| Mode/profile | Ordered system resources |
|---|---|
| general/law | SYSTEM → legal-researcher → law-question |
| case/research_cache | SYSTEM → research-cache |
| brief/prior_briefs | SYSTEM → prior-briefs |
| appeal/assess_argument | SYSTEM → legal-researcher → case-assessment |
| general/subsequent_treatment | SYSTEM → legal-researcher → subsequent-treatment |

All workflow resources are `.pi/skills/<name>/SKILL.md`, with matching names,
Agent Skills frontmatter and `disable-model-invocation: true`. Essential rules
are inline, not optional references. The wrapper rebuilds from the shared base
on each launch, including reused workspaces, and explicitly passes the assembled
file with `--system-prompt`. `--no-skills`, `--no-prompt-templates`,
`--no-context-files`, existing tool allowlists, explicit extensions, model/profile
arguments, session directory and follow-up bridge are retained. Research-capable
mode-level web availability is unchanged; treatment instructions still prohibit
web search. No new validators on legal answers or extra model retries were added.

`agent_prompts.py` has no GTK, config, or instruction-resource dependency. It
constructs only literal task/run data and shell-quoted generated commands.
`_compose_*_agent_prompt` entry points delegate without changing call sites.
Current-case context reports selection, availability/warnings and exported paths;
interpretation is shared system/workflow policy. Follow-ups do not reselect a
workflow or refresh the corpus when the composer scope changes.

## Shipped-prompt requirement mapping/review

This is a preservation review against the five shipped defaults at `8b12908`,
not a legal-answer quality claim.

| Previous location/requirement | New owner and review |
|---|---|
| General: small California-law task, federal exception when explicitly required | law-question; no jurisdiction selector or independent research procedure |
| Cache: selected materials only; no web/unselected library; SOCF-only factual questions | research-cache, Authorized materials; selected manifests/counts/paths remain request data |
| Cache: cases/enactments vs advocacy vs facts vs saved analysis | research-cache plus common SYSTEM evidence/authority distinctions; saved answers cannot supply authoritative quotes |
| Cache: meaningful factual/legal comparisons, existing record cites, no local-file cites | research-cache Comparison plus shared current-case interpretation |
| Cache: exact continuous 2–5-word quotes, same-paragraph material-specific identifiers, SOCF extracted text, advocacy/factual labels | research-cache reader-link rules preserved explicitly |
| Briefs: lookup vs research/comparison; newest substantive match, not just exact wording; no unsolicited attached-SOCF comparison | prior-briefs Select scope / Document lookup |
| Briefs: newest-first short search; plausible newer candidates resolved; 1–2 concrete gap refinements; `has_more` not an obligation to read older matches | prior-briefs Document lookup; uncertainty is narrowly disclosed, not an exhaustive claim |
| Briefs: one linked result/type/date and short explanation; ties/file-date fallback; no survey unless requested | prior-briefs Document lookup and answer rules |
| Briefs: short discriminating `all`/`phrase` searches, `any` token warning, 5–10 candidates, gap-driven stopping, complete JSON and error semantics | prior-briefs Research or comparison |
| Briefs: fetch once with workspace-confined `--output-dir`, metadata/manifest then EVERY lossless part to EOF, late adverse text | prior-briefs Source verification; fetching/grep are not full inspection, chunk numbers not pinpoints |
| Briefs: exact full Markdown links, 2–10-word continuous quotations, no bracket rewrites; ranked recommendations only for research | prior-briefs Source verification and answer rules |
| Briefs: advocacy attribution, child/adult/nondependent/trial/appellate distinctions, companion duplication, narrow coverage caveats | prior-briefs Source verification and answer rules |
| Assessment: neutral California appellate bench memo, not advocacy or question-premised outcome | case-assessment opening / Analysis |
| Assessment: supplied fact pattern is complete record, read first; no generic missing-record caveat; specific consequential ambiguities only | case-assessment Factual record; source paths are runtime data |
| Assessment: actual record cites near supported claims; no invented pinpoints/local paths; express issue-specific focus | case-assessment Factual record / Research and analysis |
| Assessment: five memorandum sections; strongest reasoning on both sides; material preservation/prejudice/remedy; direct answer | case-assessment Bench memorandum / Analysis |
| Assessment: final Conclusion/Confidence lines and calibrated High/Medium/Low meanings | case-assessment final section, retained verbatim in substance |
| Treatment: graph once; if necessary exact citation then exact name searches only; no query rewriting, pagination, semantic/web search, timeout retries | subsequent-treatment Discovery ceiling; exact commands generated in Python, including quoted title/citation/cluster arguments |
| Treatment: confirmed SQLite startup lock retry only; no replay of recovery outcomes | subsequent-treatment plus unchanged Legal Researcher transient-lock contract |
| Treatment: 3–5-case ceiling not quota; published verified later cases; parallel compact baselines; one sequential recovery per authority across aliases | subsequent-treatment Discovery / Extraction plus shared bounded execution |
| Treatment: citation preferred, cluster alternative only when needed; no recovery on already paginated reconciliation; at most one ordinary full extraction | subsequent-treatment Selected-case extraction; Python supplies templates |
| Treatment: supported treatment only, useful unpaginated baselines, returned URLs, missing pagination/citation/text caveats, no alternate-source hunts | subsequent-treatment Citation/fallback/disclosure |
| Shared: narrow enactment-only route, mandatory published-case route, direct `--find`, same-round work, source verification, bounded recovery | Legal Researcher retained; no weakening of case floor or source routing |
| Duplicated treatment ceiling | detailed ceiling now only in subsequent-treatment; Legal Researcher delegates and retains shared verification/recovery |
| Duplicated assessment record/structure rules | case-assessment; Legal Researcher delegates |
| Conflicting title limit | SYSTEM's stricter 3–8 words / 64 characters everywhere; subtitle 2–5 words / 40 characters; assessment example now also fits |
| Current-case interpretation formerly in Python | compact common SYSTEM rule; Brief lookup exception and assessment complete-record rule remain workflow-specific |

The common SYSTEM remains a compact identity/source/workspace/honesty/presentation
contract, not a second legal-research procedure. No user-supplied values format
skill files. Source material remains evidence rather than executable instructions.

## Configuration compatibility

The five current JSON prompt keys plus `later_treatment_agent_prompt_template`
are inactive `retired_prompt_settings` (`repr=False`). Load preserves key presence
and JSON values, including whitespace, malformed template strings, nulls, lists,
objects, booleans and both treatment aliases together. It never selects an alias,
normalizes a command, inserts a prompt default, fingerprints or upgrades a prompt.
Fresh Settings saves add no prompt keys. Explicit saves carry loaded compatibility
data forward while updating active preferences. Existing profile versioning and
retired preset compatibility are unchanged (AST comparison confirmed that only
`load_config` and `save_config` changed semantically among configuration helpers).
Unused prompt normalization/fingerprint helpers had no remaining callers and were
removed from `agent_commands.py`; the canonical CLI prefix helper remains.

**Intentional change:** former custom prompt settings no longer influence new
sessions. No deployment command touches real `config.json`. Its private SHA-256
was compared before/after work without printing its contents or hash: unchanged.
No case materials, user sessions or provider credentials were used for acceptance.

## Isolated automated acceptance

Disposable root: `/tmp/oll-workflows-kmn52lq6` (local, not a synced runtime).
Only Git-listed source and new implementation files were copied; no ignored
`.venv`, config/cache/library/prior-brief/session directories were copied.
Provisioning used the absolute UvEnvironments helper with paired
`--project /tmp/oll-workflows-kmn52lq6/source` and
`--environment /tmp/oll-workflows-kmn52lq6/env` overrides, locked Python 3.13.
Execution used those same overrides, with synthetic config/cache/library/archive,
XDG state/cache paths and no `COURTLISTENER_TOKEN`. Sibling PiRunMetrics was
referenced read-only for existing offline observer tests; its source was unchanged.

Checks:

- Full documented `python -m unittest discover -s tests`: **1,120 tests PASS**
  (16.1 seconds after the shared-boxed-list correction).
- Actual wrapper with all five real resource combinations: exact ordered
  assembly once, rebuilding on reused workspace, mode-derived defaults, Law vs
  Treatment distinction, missing/empty/unreadable resources and invalid pairs
  rejected before fake Pi execution.
- Installed offline Pi SDK with synthetic provider and forbidden network:
  all five workflows, initial requests and follow-ups; identical original
  instructions throughout, literal input survives, tool confinement and completed
  JSONL/Answer transport unchanged. Observer enabled/disabled/missing/unwritable
  variants compare prompts/tool content exactly; only timestamp and nondeterministic
  SDK tool-result `durationMs` are normalized. No live API calls.
- Pure builders: selected paths/counts/states/warnings, assessment paths,
  authority-count compatibility, treatment command templates, shell tokenization
  for punctuation/quotes/Unicode/metacharacters/cluster IDs, literal braces and
  slash-like text. Private request-file write/read also preserves literal input.
- Assembled instruction contracts: shared routing/recovery/verification and title
  limits, closed corpus, cache quotes, prior-brief lookup/full verification/links,
  neutral complete-record assessment, bounded treatment and supported fallbacks.
- Synthetic config read-only/load/save round trips: absent/present keys, both
  aliases, all JSON shapes, old defaults/custom prose, active preferences and
  all five profiles. No retired text enters live request/instruction assembly.
- Model controller: independent profiles, capability clamping, unavailable models,
  failure retention, stale close guard. A pending-profile snapshot additionally
  prevents an unsuccessful refresh from reverting unsaved profile choices.
- Five new Agent Skills passed the bundled skill-creator validator with existing
  system PyYAML; no dependency installation was needed.
- Syntax: 127 Python package/test files compiled in disposable source; wrapper
  `bash -n` and implementation `git diff --check` passed.

Early failures were updated assertions expecting old instructions in request
text, and an existing observer equality test comparing variable SDK tool wall
time. No legal-source restrictions were relaxed to make tests pass. Current Pi
represents provider instructions as transcript system messages/sections; offline
acceptance now checks that actual representation as well as older SDK shorthand.

## Native Settings acceptance

The following records the initial five-category workflow change and boxed-list
correction. The later [source-location update](settings-source-locations.md)
moves Fact Pattern into General, adds Prior Briefs Folder, and leaves **four**
category rows in the same shared boxed list.

`tests/preview_settings.py` creates the **actual** updated SettingsWindow, a
minimal synthetic parent, temporary settings and synthetic source paths, and a
mock asynchronous catalog. It never opens a live case, model or network source.
`--auto` exercises native widget state, explicit save/error/reload and callbacks;
`--matrix` produces native widget renderings (not desktop screenshots).

Verified:

- ONE shared rounded boxed list containing all five initially collapsed category
  rows, no sidebar/stack or prompt TextView, independent simultaneous expansion
  and unsaved-value retention. Like Focus, one outer PreferencesGroup owns every
  category ExpanderRow; model/reasoning remain ComboRow dropdowns in five labeled
  groups within Agent Models, not nested workflow expanders.
- One application-owned outer scroller; all controls share it. Model popover
  scrollers are toolkit-owned menus, not extra settings-page scrollers.
- Five profiles, one configured unavailable model, long Unicode model labels,
  mock loading/refresh success/failure, preserved unsaved choices, close-generation
  invalidation, token masking, native GTK focus traversal, synthetic save/error/reload
  and untouched retired JSON.
- Temporary fact-pattern choose/reset callbacks; selection changes the parent
  session override immediately and survives closing without persistent Save.
- Render matrix: collapsed/expanded 900×760 light, expanded 900×760 dark,
  expanded 620×760 dark with 20px text, and bottom-of-page view reaching all five
  model groups. No horizontal scrolling; selected long labels ellipsize and
  subtitles wrap as needed. Rendered controls remain within the window.
- After the desktop was unlocked, Linux Computer Use observed the real synthetic
  window at 900×760, expanded Case Question and Agent Models simultaneously,
  opened a model dropdown, and visually confirmed masked token/concordance rows.
  No other app/document/session was controlled or closed.

Limitations: targeted keyboard events were dispatched, but did not yield a
verified selection/focus change through this local input backend; physical
keyboard/end-to-end key injection is not claimed. Native GTK focus traversal is
checked by the preview separately. The chooser completion/reset callbacks use
synthetic Gio files; an operating-system chooser selection is not claimed.
GTK Vulkan swapchain warnings appeared during resizing; native state checks and
renders completed successfully with no application traceback. Closed/default
window sizes can be affected by local window-manager placement; final matrix
asserted the actual 900×760/620×760 allocations.

No paid legal-answer quality evaluation was performed. Instruction contracts and
structural/GUI checks are not a guarantee of model compliance or legal accuracy.
Historical quality-run scripts were updated to build candidates from current
app-owned resources; they remain opt-in and were not executed.

## Shared-boxed-list correction (2026-10-16)

Jesse correctly rejected the first layout: it put each category in a separate
PreferencesGroup/card, unlike Focus's single shared list. Earlier visual
acceptance did not check this requirement precisely enough. The correction
creates the outer PreferencesGroup once, before the category loop, and adds all
five ExpanderRows to it. Outer top/horizontal margins also match Focus (18px).
Controls, callbacks, model profiles, persistence and agent instructions are unchanged.

- Added a native regression asserting that all five category rows have the SAME
  boxed Gtk.ListBox parent, in the expected order, with exactly five rows. It
  fails on the previous implementation (exit 1) and passes on the correction.
- Added a unit guard against creating/appending a group inside the category loop.
- Corrected the preview's failure reporting so failed auto assertions return a
  nonzero process exit, rather than only printing a GTK callback traceback.
- Full suite: 1,120 PASS. Native auto scenario: three consecutive PASS runs.
  One earlier corrected-layout attempt failed the initial-collapsed assertion;
  cause not established, no app reset/retry behavior added. Subsequent runs pass
  that assertion without weakening it; its diagnostics now name expanded rows.
- Reran and reviewed the light/dark 900×760 and enlarged-text 620×760 matrix,
  now with explicit allocation assertions. All five stages passed, with no
  horizontal scrolling. Screenshots show one contiguous surface with separators,
  and expansion inside that surface.
- Linux Computer Use visually confirmed the real synthetic window's single
  shared list and Display controls opening within it. Further desktop interaction
  was stopped when foreground observation changed unexpectedly; no claim is made
  for that ambiguous final input. Only the synthetic preview process was stopped;
  the user's already-running OpenLawLens/Settings windows were left untouched.
- Evidence logs: `/tmp/oll-shared-boxed-4gkatjqp`; native matrix images:
  `/tmp/oll-settings-preview-4l_3m_8q`. Existing disposable source/environment reused;
  production settings remain byte-for-byte unchanged.

## Rollout and rollback

Deliver Python, wrapper and `.pi` resources together. Restart the GUI and start a
new Agent session to receive the new layout/instructions; existing sessions and
saved answers are not interrupted, rewritten or relabeled. Follow-ups keep their
original instructions/corpus. There is no production dependency sync, migration,
cache/library cleanup, settings rewrite or deployment step. Rollback restores
prior code/resources; retained prompt values remain available to that version.

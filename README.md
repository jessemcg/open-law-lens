# Open Law Lens

The five Pi workflows now share sibling `PiRunMetrics/launch_adapter.py` via system Python for bounded executable-only version/Git probes. Collection requires Pi >=0.87.1; unavailable/incompatible collection warns and fails open without upgrades. Source-project archive resolution ignores staged config roots and replaces inherited parent-app tags. Web/tool confinement, JSONL answer transport, generation guards and Save remain unchanged. New embedded launches use the adapter. Sibling **Pi Run Metrics** provides readiness, private reports and an existing-session PiPlanner request; it never launches models or migrates archives.

<img src="open-law-lens-icon.png" alt="Open Law Lens icon" width="128" align="left">

Open Law Lens is a practical legal research app for working with public legal
authority through open tools. The app currently focuses on California state
law, with first-class workflows for California cases, California statutes, and
the California Rules of Court. The scope may expand in the future. It is built
around CourtListener, local caching, an inspectable SQLite library, a
GTK/Libadwaita reader, and terminal-friendly CLI commands that can be used
directly by people or by Pi.

The goal is to make legal authority easier to inspect, reuse, and
research without depending on large commercial platforms. Court opinions,
statutes, and court rules are public legal materials. Open Law Lens is intended
to help lawyers, researchers, and technically curious users work with those
materials in a transparent local workflow, starting with California state-law
research.

## CourtListener and Free Law Project

Open Law Lens relies on [CourtListener](https://www.courtlistener.com/) for case
law search, citation lookup, opinion metadata, opinion text, and citation graph
data. CourtListener is a project of [Free Law Project](https://free.law/about/),
a 501(c)(3) nonprofit that uses technology, data, and advocacy to make the legal
ecosystem more open, and equitable.

CourtListener provides legal APIs for developers and researchers. Some API
endpoints can be explored without authentication, but Open Law Lens users should
create a CourtListener account and use an API token for regular use. The token
improves reliability, makes throttling more predictable, and is required for
some workflows.

Get your token from your CourtListener profile:

https://www.courtlistener.com/profile/api-token/

Then either export it before running Open Law Lens:

```bash
export COURTLISTENER_TOKEN="your-token"
```

Or save it in the app menu under Settings. The Settings path writes a local
`config.json` file in the project root.

## Features

- GTK4/Libadwaita desktop app with a quiet reader-focused interface.
- Citation lookup for California cases through CourtListener.
- California statute and California Rules of Court lookup.
- Pinned Current Case SOCF and brief-prep Markdown reports above the Research Cache, with per-case SOCF agent-context selection.
- Research Cache sidebar grouped as **Statutes**, **Case Law**, **Prior Briefing**,
  and **Saved Answers**, in that order. Statutes includes all supported court
  rules; saved answers from every workflow remain answers, not legal authority.
  Statute rows match the reader masthead: full code name with just `§ number`
  beneath it, rather than repeating the code in an abbreviated citation.
  Empty groups are hidden. Tinted item rows, stronger counted heading bands, and
  4-pixel teal/blue/bronze/violet edges identify categories in light and dark
  appearances. Text and controls stay neutral; persistent selection outlines and
  stronger keyboard-focus outlines distinguish state from category. Research
  Cache subtitles have stronger contrast without changing other secondary text.
  High contrast replaces category fills with neutral edges and outlined headings.
  Color does not indicate authority quality, confidence, or agent inclusion.
  This is presentation-only: rule types, citations, readers, cached data and
  existing Research Sets remain unchanged; no migration is required.
- Durable SQLite library at `library/open_law_lens.sqlite3` for saved authority
  data, display text, and reporter page-marker metadata.
- Disposable JSON API cache under `cache/`.
- Bounded subsequent-treatment agent workflow using Open Law Lens CLI citation-graph
  leads, two exact CourtListener searches, and one-attempt official-copy recovery.
- CourtListener-first baseline with a single confined default-browser Google
  Scholar recovery for official reporter text and pagination gaps.
- Reader links for cited cases, statutes, and rules.
- Named Research Cache sets.
- Exact-phrase search across the indexed prior-brief archive, with newest-first
  reader navigation through matches.
- Selected-text launcher through `open-law-lens open-selected`.
- Embedded Pi-only Agent workflow for legal research questions, selected-cache
  questions, and neutral legal question assessment.
- Assess Legal Question from a current-case SOCF or another ODT/PDF fact
  pattern, with configurable legal question presets and custom questions.

## Requirements

- Python 3.13+
- `uv`
- GTK 4, Libadwaita, and PyGObject system packages
- Required for Agent features: GTK VTE packages and the Pi coding agent
- Optional: `pdftotext` for extracting appeal fact patterns and California
  slip-opinion PDFs

Ubuntu/Debian package names vary by release, but the GTK stack is typically
provided by packages such as:

```bash
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 poppler-utils
```

Install or sync the Python environment with:

```bash
uv sync
```

### Install and Authorize Pi

Open Law Lens uses only the
[Pi coding agent](https://pi.dev/docs/latest) for its Agent features. Follow
Pi's official documentation at that link to install it. Open Law Lens does not
invoke the Codex CLI or provide another coding-agent backend.

Before running an Agent query in Open Law Lens, start Pi in a separate terminal
session and authorize each model provider you want to use. For subscription
providers, run `/login` inside Pi and follow its prompts. Pi also supports API
key providers as described in its documentation. Complete this authorization
in Pi itself; do not enter model-provider credentials into Open Law Lens.

Pi stores persistent model authorization in its user-level configuration,
including `~/.pi/agent/auth.json`. The embedded VTE terminal runs Pi as the same
user, so its Pi session inherits those authorizations. Open Law Lens does not
copy model credentials into the project or its temporary Agent workspaces.

The embedded Agent defaults to `openai-codex/gpt-5.6-sol`, which is a model
provider and model selected through Pi; it does not mean that Open Law Lens
uses the Codex coding agent. Install the user-level `pi-web-access` package for
research-capable Agent workflows:

```bash
pi install npm:pi-web-access
```

Open Law Lens explicitly loads that package from Pi's user agent directory
while keeping unrelated extensions disabled. This uses the same package updates
and `~/.pi/agent/web-search.json` credentials as ordinary Pi sessions. The launcher
also uses the Node runtime installed alongside Pi instead of the desktop
session's system Node.

Default-browser Google Scholar recovery is deterministic and requires only the
user-level `@agent-sh/computer-use-linux` package (tested with `0.4.9`). Run
`computer-use-linux doctor` and confirm no readiness blockers:

```bash
pi install npm:@agent-sh/computer-use-linux
computer-use-linux doctor
```

`pi-mcp-adapter` is no longer used for Scholar recovery.

The Settings window lists the models currently authorized in Pi and lets each
user choose a separate model and reasoning effort for Query Law, Query Research
Cache, Query Prior Briefs, and Assess Legal Question. These personal overrides are
stored in the ignored local `config.json` and apply to newly launched sessions.
Choosing **Use Pi defaults** leaves that workflow on Pi's merged user and
project defaults. Pi credentials remain in the user's home Pi configuration,
and the tracked `.pi/settings.json` remains the project fallback.

## Run the App

Launch the GTK app:

```bash
uv run open-law-lens app
```

Open an authority directly:

```bash
uv run open-law-lens open "In re Caden C. (2021) 11 Cal.5th 614"
```

Open the first authority found in the current OS selection or clipboard:

```bash
uv run open-law-lens open-selected
```

## CLI Commands

Open Law Lens exposes its research tools through the `open-law-lens` command.
The CLI is meant to be useful both to humans in a terminal and to coding agents
that need predictable JSON/text outputs.

Show the full command surface:

```bash
uv run open-law-lens --help
```

Show the agent-oriented command list with examples:

```bash
uv run open-law-lens --list-cli-commands
```

Common California-focused examples:

```bash
uv run open-law-lens lookup-citation "11 Cal.5th 614"
uv run open-law-lens lookup-citation "11 Cal.5th 614" --text
uv run open-law-lens extract-case "13 Cal.4th 952"
uv run open-law-lens extract-case "13 Cal.4th 952" --find "presumed father"
uv run open-law-lens case-search "beneficial relationship exception" --limit 5 --compact
uv run open-law-lens extract-statute "Welf. & Inst. Code, § 300"
uv run open-law-lens extract-rule "Cal. Rules of Court, rule 8.1115"
uv run open-law-lens published-citing-cases --cluster-id 6240402 --limit 10 --json
```

`extract-case` supplies the Library/CourtListener/slip baseline. Its JSON
includes `official_pagination` and `pagination_marker_count`; use `--refresh`
to bypass saved Library/CourtListener/slip lookup data:

```bash
uv run open-law-lens extract-case "20 Cal.4th 1135" --refresh
```

For narrow verified propositions and quotations, `--find` (repeatable) returns
bounded exact source passages instead of the full opinion. The compact payload
omits the full `text` field, keeps citation, source, warnings, `text_length`,
and pagination metadata, and returns every passage with its original offsets,
matched query names, and conservatively attributed reporter pages:

```bash
uv run open-law-lens extract-case "13 Cal.4th 952" --find "presumed father" --find "biological father"
```

`--find` is mutually exclusive with `--text`. Passing no `--find` keeps the
ordinary full-JSON `extract-case` output unchanged. Whole-match windows are
allocated in query rounds (one match per query before second occurrences),
within two matches per query, six passages, 2,000 characters per passage and
12,000 passage characters total. `query_accounting` distinguishes source totals,
returned matches, and omissions; `unmatched_queries` means genuinely absent,
not omitted by output limits. `match_count` counts only contained verified
matches. Oversized matches are omitted, never advertised partially.

`pinpoint_status` is `available`, `ambiguous`, or `unavailable`. Only a single
coherent official reporter sequence supplies pages; mixed/descending markers
leave page fields empty. The opinion-level `official_pagination` flag does not
prove that every marker belongs to that reporter. Passage `page` describes the
passage start; matches have their own `start_page`/`end_page`. Ambiguity does not
trigger another Scholar recovery or rewrite stored markers. Use the verified
citation and source URL without guessing a pinpoint.

Lexical and semantic searches validate delivered court IDs and publication
status locally. Scoped searches exclude unknown/mismatched courts; published
status is required unless `--include-unpublished` is specified. `--court` and
`--all-courts` retain their overrides. `total_count` remains the upstream count,
labeled `total_count_scope: upstream_unverified`; `result_count` counts delivered
rows. Exclusion reasons and coverage warnings disclose incomplete coverage;
no replacement pages are fetched. Opt-in `--compact` limits each snippet to
1,200 characters with truncation diagnostics; default snippets are unchanged.
Keep complete JSON: use CLI bounds, never `head`/`tail` on research results.

Statute parsing recognizes all 29 California LegInfo codes, their California
Style Manual abbreviations, uppercase identifiers, and common aliases including
`Educ. Code`, `Gov’t Code`, `Cal. Civ. Proc. Code`, and `W&I`.
Bare lookup inputs such as `300`, `section 300`, and `§ 300` do not default
to any code. Specify the code explicitly. The old bare-number code preference
has been retired; legacy configuration values are ignored. Unsupported, conflicting, or malformed qualified
citations fail closed. LegInfo extraction
requires a matching section body and rejects conflicting identity or navigation
alone before authority caching. Failures retain nonzero CLI exit and `ok: false`.
Previously cached bad authorities are not deleted or migrated; handle those
manually rather than assuming this update repairs existing saved research.

Uncited `--cluster-id` extraction reconciles against the durable Library before
any fallback. When the requested CourtListener cluster is unpaginated, Open Law
Lens first checks for one unambiguous, officially paginated durable Library
case that is the same opinion stored under a different cluster identity (for
example a validated Scholar import). Reconciliation uses the exact official
citation when the incoming cluster carries one, or otherwise an exact
normalized case title plus an equal filing year; conflicting years, differing
titles, missing years, duplicate candidates, or copies without qualifying
reporter markers reject the match rather than guess. A successful
reconciliation returns `source: "Library"`, keeps the requested cluster ID in
`resolved_input` and the durable case ID in `identifier`, reports the durable
case's citation, text, marker count, and stored provenance URL, suppresses any
Scholar recovery suggestion, and is a read-time alias decision only — stored
IDs are never merged, reparented, or rewritten. `--refresh` bypasses
reconciliation and follows the requested CourtListener cluster directly.

Maintenance and inspection commands:

```bash
uv run open-law-lens show-library
uv run open-law-lens show-cache
uv run open-law-lens show-research-sets
uv run open-law-lens save-research-set "Case Name_research"
uv run open-law-lens load-research-set "Case Name_research"
uv run open-law-lens cache-dir
uv run open-law-lens library-db
uv run open-law-lens clear-cache
uv run open-law-lens prune-library
```

## Agent Queries

Open Law Lens uses only the Pi coding agent for Agent queries. It launches Pi in
an embedded terminal and directs it to use the project-local legal-researcher
skill and Open Law Lens CLI commands for CourtListener-backed research.
Project-local `.pi/settings.json` selects `openai-codex/gpt-5.6-sol` by
default, while authorization comes from the user's existing Pi configuration
as described above.

This agent workflow does not rely on the CourtListener MCP server. That is an
intentional design choice. The CLI path keeps the app more responsive, easier to
install, and less dependent on extra runtime services while still tying legal
authority lookup to CourtListener APIs and the app's local cache/library model.

There are four main agent workflows:

- Law: ask a California legal research question. The default prompt directs
  Pi to search and extract authority through Open Law Lens CLI commands. If
  the pinned current-case SOCF is checked, the app also exports it as factual
  context for that question.
- Cache: ask about authorities marked in the current Research Cache. The app
  exports the selected authorities into a temporary workspace. The pinned
  current-case SOCF is added only when its checkmark is active. Pi treats the
  marked authorities as legal authority and the SOCF as factual context,
  allowing comparisons such as which marked case is most analogous to the
  current case. A checked SOCF can also be used by itself for a factual Cache
  question.
- Prior Briefs: ask a closed-corpus question across the indexed ODT prior-brief
  archive. This remains separate from Research Cache questions and does not use
  web search.
- Assess Legal Question: assess a neutral legal question against an ODT or
  PDF fact pattern. The app extracts the fact pattern into a temporary
  workspace, launches Pi in Appeal mode, and directs it to research
  California law through the preloaded Legal Researcher workflow.

The separate **Search Briefs** scope performs a local, non-LLM exact-phrase
search. It opens matching briefs newest-first in the main reader without adding
them to the Research Cache. Use `Ctrl+S` to activate this mode, then `Ctrl+G`
and `Ctrl+Shift+G` to move forward and backward through occurrences across
matching briefs. While a match is displayed, the reader toolbar's **Add prior
brief to Research Cache** button (bookmark icon) saves that brief to the
Research Cache without leaving the search; the button stays hidden once the
brief is in the cache.

Agent runtime settings, including the five per-query Pi model/reasoning
profiles, prompt templates, appeal legal questions, and fact-pattern source,
are available in the app Settings window. Subsequent Treatment has its own
profile, independent of the Query Law profile. Each profile override is stored
locally in the ignored `config.json` file, affects newly launched sessions,
and can independently be set to **Use Pi defaults**. **Search Briefs** is
local and does not launch Pi.

Law, Subsequent Treatment, and Assess Legal Question runs are research-capable.
The launcher preloads the tracked legal-researcher skill into the disposable
workspace's system prompt once (instead of passing `--skill` and spending a
model turn reading the file), keeps `--no-skills` so no other skills load, and
loads the user-level `pi-web-access` extension. Agents route by source through
an explicit gate in that skill. There is a narrow enactment-only exception,
reserved for requests that remain entirely textual (current statutory or rule
text, a citation, or an effective date) with no further definition or
consequence; everything else takes the mandatory enactment-plus-case route.
Every definition or explanation of a legal status, doctrine, test, standard,
or term of art — and any question touching scope, application, biology, burdens,
rebuttal, conflicts, exceptions, rights, duties, or practical consequences —
requires successfully extracting and citing at least one leading published
California case. A "simple what is" question like "what is a presumed father"
shortens the answer length but never waives that published-case floor or lets
the agent silently treat statutes alone as sufficient. On the mandatory route,
a known material case is direct-extracted with `extract-case --find` for narrow
propositions in the same tool round as the statute extractions, and a focused
`case-search --limit 5 --compact` is run only when no reliable citation or name is
already known. Pi's `web_search` remains available only for unresolved,
open-ended verification after those deterministic fallbacks. This agent-facing
web search is separate from the confined default-browser Scholar official-copy
recovery described below, and is never used to retrieve an official reporter
copy. Research Cache and Prior Brief runs load no skill and no web extension
and remain closed-corpus workflows.

All research-capable modes also follow the skill's bounded execution contract:
180-second bash tool deadlines, sequential 120-second recovery with progress,
complete JSON stdout and separate stderr, preserved baselines, and one attempt
per authority across identity aliases. An unexplained abort or desktop-readiness
failure suspends further Scholar attempts for that run; agents report observed
failures rather than inventing a no-display explanation. Phrase-based `--find`
queries require match accounting and source review, not semantic paraphrases or
metadata-only summaries. These bounds do not weaken the mandatory case-law floor,
expand Subsequent Treatment discovery, or open closed-corpus modes. The system
prompt no longer advertises a retired agent-driven browser bridge.
See [research execution validation](docs/research-execution-validation.md).

Subsequent Treatment is hard-bounded. The runtime prompt supplies one
`published-citing-cases` command, at most two exact-phrase `case-search`
commands (official citation first, then case name), and ready-made
`extract-case` templates, and the prompt and preloaded skill forbid retrying
network timeouts, paginating, broadening queries, using semantic search, or
falling back to generic web search, manual `extract-slip-opinion`/`lookup-citation`
calls, Scholar orchestration, or alternate opinion sites. Three to five
verified later cases is a ceiling and a preference — fewer verified cases plus
a disclosed coverage caveat are preferable to open-ended searching. Compact
`extract-case --find` baselines run in parallel; each unpaginated selected
case gets at most one sequential `--recover-official --timeout 120 --progress`
extraction, subject to the execution-failure stop rule above. It performs Open
Law Lens's own single Scholar attempt. Recovery templates prefer a known
official citation and use the cluster-ID alternative only if none is available;
the two fixed discovery searches now request compact results. An unpaginated
selected case that reconciles against a durable official copy (see
Official-Copy Source Order below) is returned immediately from the Library and
never launches Scholar. Unsuccessful Scholar recovery yields the linked
CourtListener/slip baseline with a disclosed pagination limitation — never
another source search — and unsupported treatment characterizations are
omitted rather than inferred.

The immediately preceding exact shipped Subsequent Treatment default upgrades
in memory on config load; customized prompts and all model profiles are
preserved, and no settings file is rewritten. Start a fresh Agent session for
the skill/system updates and restart the GUI for generated-command changes.

The wrapper also resolves `uv` deterministically before launching Pi. It uses
the validated `OPEN_LAW_LENS_UV_BIN` override, then `uv` on `PATH`, then
`$HOME/.local/bin/uv`, and prepends the resolved directory to `PATH` so the
canonical `uv run --project "$OPEN_LAW_LENS_PROJECT_DIR" --no-sync ...`
commands work even under a reduced desktop `PATH`. If `uv` cannot be resolved,
the wrapper fails before any model work with a concise diagnostic.

Pi remains in a private disposable workspace rather than using the source tree
as its working directory. Agent-facing Open Law Lens commands explicitly select
the installed project with this canonical prefix:
`uv run --project "$OPEN_LAW_LENS_PROJECT_DIR" --no-sync open-law-lens ...`.
This keeps command resolution deterministic without exposing the project tree
through ordinary workspace discovery.

Final-answer completion keeps GTK responsive: session-log reading, source/quote
matching, and text/link preparation run in a background worker; GTK inserts and
formatting are applied in short main-loop batches. **Preparing final answer…**
keeps its spinner active after the agent exits until formatting and layout have
been handed back to GTK. Stale work from a replaced session or closed window is
ignored. Failures leave the Session output available rather than keeping a
spinner running forever. See [completion validation](docs/answer-completion-responsiveness.md).

Live and saved answers render nested bold/italic Markdown (including italic
case names inside bold citations) without showing delimiter stars. Citation
links preserve explicit bold formatting. Existing saved answers benefit when
reopened after restarting the app; no stored-answer migration is needed.

Saved agent answers begin with an issue-specific title and compact disposition
subtitle. Open Law Lens uses those fields in the Research Cache sidebar and
enforces short sidebar-friendly limits: at most eight title words and five
subtitle words, with a 40-character subtitle cap. If an older or nonconforming
answer omits this metadata, a newly saved answer uses the original question as
its title when available rather than treating prefatory model language as the
title.

The pinned Current Case section is separate from Research Set contents and
cannot be removed by clearing the Research Cache. Its first row displays the
same normalized SOCF text supplied to the agent in the main reader. The SOCF
context checkmark starts off for each case and remembers that case's choice
across app launches. Assess Legal Question always includes its selected fact
pattern, regardless of this ordinary-question checkmark.

Open Law Lens also searches the selected case directory recursively for
`suggested_reply_arguments.md`,
`suggested_respondents_brief_arguments.md`, and
`suggested_opposition_arguments.md`. Every matching file appears below the
SOCF section, with its case-relative path shown so duplicate copies remain
distinguishable. The list refreshes when the app opens, regains focus, or the
Current Case refresh button is clicked. Legacy HTML reports and the separate
OmniVoice `.txt` companions are not listed.

Clicking a suggested-arguments row renders its Markdown in the main reader.
Recognized case citations, California statutes, and California Rules of Court
use the same automatic authority links as other reader content. These reports
are display-only and are not added to Law, Cache, Prior Brief, or Appeal agent
context.

When the Current Case SOCF is open, a collapsible Outline appears beneath its
sidebar row. The outline preserves the ODT heading hierarchy and each entry
jumps directly to that section of the reader. It is independently scrollable
so the Research Cache remains available below it. Headings and subheadings are
rendered in bold in the SOCF reader.

### California statute and rule links

Case opinions, saved answers, cached enactments, prior briefs/search views,
Current Case documents, and live final answers share one pure authority-link
collector. It recognizes full/abbreviated code names, plural lists, written range
endpoints, subdivisions, reverse citations, and modern statewide rules including
`CRC 5.112.1`. Lists link only explicitly written sections/rules, never implied
sections. Clicking retrieves the whole current official section/rule, not a
historical version or a subdivision anchor. Rendering performs no retrieval or
cache writes; successful on-demand government retrieval goes to **Research
Cache**, never the durable case library. Research Set saving is unchanged.

Undesignated statutory references require an explicit, unquoted document
code declaration, a preceding same-section reference in the same paragraph
without conflicting authority, the displayed statute’s owning code, or verified
Juvenile Rule membership under rule 5.502(36). The active Division 3 membership
snapshot and official-source provenance are in `citation_context.py`; other
Title Five rules do not imply WIC. Conflicting declarations disable document
inference. Each separate opinion is scanned independently; answers and briefs
never inherit a source opinion’s declaration. Ambiguous, historical/renumbered,
foreign, federal, local, professional-conduct, and malformed citations remain
unlinked. This is conservative common-form recognition, not exhaustive citation
resolution; `id.`/`ibid.` and obsolete integer rule numbers are not converted.

Worker preparation and bounded link-tag batches reject superseded reader work,
including enactment lookups that finish after navigation or cache clearing.
Reader metadata shows the section or rule number without an extra current-text
notice. Invalid government bodies,
unrelated rule redirects, and timeouts produce errors before any authority write.
CourtListener sometimes supplies padding after opening parentheses in its HTML
(e.g., `( People v. …)`). Opinion display normalization removes that padding and
remaps page-marker, heading, and citation offsets. Restart and reopen existing
content to gain these display fixes; stored text and old cached records are not
rewritten or migrated.

`tests/preview_enactment_links.py` launches a separately identified synthetic
acceptance window with fresh temporary state. See
[enactment link validation](docs/enactment-links-validation.md) for automated,
desktop, and official-source checks.

### Reader masthead

The reader keeps the title and citation/subtitle centered, with a small muted
source at the upper left and unchanged actions at the right. Ordinary provider
names remain fully visible; long external-web descriptions are ellipsized, with
complete accessible text and a hover tooltip. Navigation clears source details.
The title remains 13 pt semibold; metadata is 10.5 pt and source text 9.5 pt.
No stored content or settings are changed.

`tests/preview_reader_masthead.py --auto` checks the production masthead in a
separately identified synthetic window with temporary state. See
[masthead validation](docs/reader-masthead-validation.md) for coverage and limits.

### Reader Copy Citation

With text selected, the reader’s **Copy Citation** button copies only the complete
citation with the selection’s page, page-range, or subdivision pinpoint—not the
selected prose. It preserves case-name italics for rich-text pasting and provides
a plain-text alternative, without adding quotation parentheses or a terminal
period. If no pinpoint can be determined, it warns and leaves the clipboard
untouched. Without a selection, it copies the full citation as before. Use
ordinary **Copy** to copy selected prose.

### Operational metrics pilot

Copy Trace is removed. **Answer**, **Session**, and **Save** remain. Workspace-local
Pi JSONL remains the internal answer transport, with the existing session discovery,
background rendering, and generation guards; it is not exported to the metrics archive.
Old saved traces and private settings are untouched.

All Pi-backed modes explicitly load the sibling `../PiRunMetrics/run-collector.ts`
without changing models, prompts, web access, or tool restrictions. Workflow tags are
`law`, `research_cache`, `prior_briefs`, `assess_argument`, and `subsequent_treatment`.
Local **Search Briefs** launches no Pi process and creates no metric record.

New sessions save content-free operational records inside this project:

```text
OpenLawLens/.run-metrics/runs/YYYY-MM-DD/<run-uuid>.jsonl
```

The entire `.run-metrics/` directory is Git-ignored. Directories/files remain private
(`0700`/`0600`), but Dropbox may sync them because the project is under Dropbox;
Git ignore is not a Dropbox exclusion. No prompts, answers, thinking, transcripts,
tool arguments/results, or error prose are stored there. Jesse alone assesses quality.

From the OpenLawLens directory, generate an on-demand batch report:

```sh
python3 ../PiRunMetrics/analyze_runs.py --root "$PWD/.run-metrics/runs" --app open-law-lens --days 14
```

Reports remain in private XDG state. An absolute `PI_RUN_METRICS_ROOT` overrides the
archive path; `PI_RUN_METRICS_COLLECTOR` overrides the collector file. Missing collector
code or telemetry failures warn without blocking research. Set `PI_RUN_METRICS_ENABLED=0`
to disable collection. Restart the app to remove the button; new embedded sessions
load the observer. Receiving computers need the sibling project and compatible Pi
(offline tests use 0.87.1). Rollback never deletes archives. See
[acceptance notes](docs/run-metrics-acceptance.md) and PiRunMetrics README for limits.

## Assess Legal Question

The Assess Legal Question workflow produces a neutral, decision-oriented
California appellate assessment of a supplied legal question — similar to a
bench memorandum written for the appellate court — rather than advocacy for
either side. It is available from the visible **Assess Legal Question…** menu
in the Research composer heading. The menu includes assessment actions for
configured legal question presets, a custom assessment action, and a shortcut
to edit the appeal legal question settings.

Presets and custom entries are neutral legal questions, not claims or
arguments. The nine built-in dependency presets are questions such as "Did
substantial evidence support the challenged finding?" and "Did the juvenile
court abuse its discretion in finding that the child welfare agency conducted
an adequate Cal-ICWA inquiry under Welfare and Institutions Code section
224.2?". The custom action accepts a multi-sentence question plus any
issue-specific focus, for example:

```text
Did the juvenile court abuse its discretion in finding that the child welfare
agency conducted an adequate Cal-ICWA inquiry under Welfare and Institutions
Code section 224.2? Address expressly the significance of the fact that no one
claims ancestry with a particular tribe.
```

By default, Open Law Lens tries to use the SOCF ODT for the currently selected
case. The Settings window can point the workflow at a different fact-pattern
ODT or PDF. ODT files are read directly; PDF extraction uses the system
`pdftotext` command.

When an assessment starts, the app copies the source fact pattern into a
temporary agent workspace, writes an extracted text file, and launches Pi in
the embedded terminal. The default assessment prompt asks Pi to act as an
objective California appellate court deciding the supplied legal question, not
as an advocate for either side, and not to presume an answer from the
question's wording. It treats the selected fact pattern as the complete
factual record and prohibits speculation about a more complete record or a
generic record-completeness caveat. A concrete ambiguity, contradiction, or
missing record citation in the supplied text may still be addressed where it
affects the analysis. The answer follows a concise bench-memorandum structure
(Question Presented, Short Answer, Governing Law/Standard of Review, Analysis,
Conclusion) and applies the law neutrally, addressing the strongest material
reasoning supporting each possible answer. Preservation, prejudice, harmless
error, and remedy are addressed when legally material, not as a mechanical
checklist. The answer always ends with a direct conclusion and a calibrated
confidence line:

```text
Conclusion: <direct answer to the legal question>
Confidence: <High, Medium, or Low> — <brief basis tied to the law and record>
```

Confidence describes confidence in the stated conclusion — not argument
strength or a party's likelihood of success. High means controlling law and
the material record strongly point the same way with no meaningful unresolved
conflict; Medium means one conclusion is better supported but a substantial
counterargument, factual ambiguity, or authority tension remains; Low means
the issue is close or unsettled, or a material source or record ambiguity
prevents a firm conclusion.

The workflow is intentionally research-oriented. Pi follows the preloaded
Legal Researcher workflow, which directs Open Law Lens CLI commands such as
`extract-statute`, `extract-rule`, `extract-case` (including
`extract-case --find` for narrow propositions), and focused `case-search`
before relying on authority, with Scholar official-copy recovery when needed.

Open Law Lens does not override Pi's thinking level per prompt. Pi's normal
project or global default applies to every agent workflow.

## Library and Cache

Open Law Lens keeps a durable SQLite authority library at
`library/open_law_lens.sqlite3` by default. The library stores raw
CourtListener JSON plus display-ready opinion text. When CourtListener provides
explicit reporter page markers, the app preserves their canonical form, such as
`[*373]`, while rendering them as subtle `[373]` badges in the reader.

The `cache/` directory is a disposable JSON API cache. Lookups check the library
first, then the JSON cache, then CourtListener. Cache or API hits are saved into
the library for faster future access.

The app sidebar is the Research Cache, not the full library. Clearing the
Research Cache removes those visible sidebar authorities while preserving the
durable library so future lookups can still be served without another API call.

For isolated test or smoke-run data, use:

```bash
OPEN_LAW_LENS_CACHE_DIR=/tmp/open-law-lens-cache \
OPEN_LAW_LENS_LIBRARY_DB=/tmp/open-law-lens-library.sqlite3 \
uv run open-law-lens show-cache
```

## United States Supreme Court Citations

Open Law Lens treats the official United States Reports reporter (`U.S.`) as
an officially paginated reporter alongside the California reporters. A United
States Supreme Court decision is accepted in the California Style Manual form
`Case Name (Year) Volume U.S. Page`, for example
`Arizona v. Fulminante (1991) 499 U.S. 279`, and is resolved, validated, and
persisted to the durable library exactly like a California official reporter
citation (CourtListener first, then the deterministic Scholar recovery when no
qualifying copy exists).

```bash
uv run open-law-lens extract-case "Arizona v. Fulminante (1991) 499 U.S. 279"
uv run open-law-lens extract-case "499 U.S. 279"
uv run open-law-lens lookup-citation "384 U.S. 436"
```

The parenthetical filing year is rendered in the California Style Manual
position (before the volume/page), and parallel reporters such as `S. Ct.` and
`L. Ed. 2d` are never substituted for the official `U.S.` citation.

## Official-Copy Source Order

CourtListener and the durable Library remain the primary case sources. Entering
a citation in the GUI, running `extract-case` (including `--cluster-id`), or
using `extract` for a detected case invokes the same resolver. When a published
California case lacks qualifying official reporter page markers, the source
order is:

1. Durable Library and CourtListener.
2. The California Courts slip-opinion display fallback when applicable.
3. One deterministic default-browser Google Scholar recovery.
4. Stop: the best CourtListener or slip text, with an explicit pagination
   warning, if no qualifying reporter copy is found.

Known unpublished cases skip the Scholar recovery and report that no official
reporter copy exists. JSON reports `official_pagination` and
`pagination_marker_count`; usable unpaginated text may still return `ok: true`
with warnings. Native Tavily discovery and direct-HTTP Scholar search were
removed; the only non-baseline official-copy path is the deterministic
default-browser Scholar recovery described below.

Before any recovery is attempted, an unpaginated CourtListener cluster is
reconciled against the durable Library: one unambiguous, officially paginated
stored case may serve as the official copy under the CourtListener identity.
Reconciliation matches the exact normalized official citation when the
incoming cluster carries one, and otherwise requires an exact normalized
canonical case title plus an equal four-digit filing year on both records.
Missing or conflicting years, differing titles, stored copies without
qualifying reporter page markers, and multiple surviving candidates all reject
the match, and the bounded fallback continues unchanged. A successful
reconciliation is reported with `source: "Library"`, `official_pagination:
true`, the durable identifier, and the stored Scholar provenance URL when one
exists, and it suppresses `--recover-official` entirely — no recovery lock, no
browser, no progress output. Reconciliation is a read-time alias decision
between existing records: it never merges, reparents, or rewrites stored
cluster IDs, and a future successful recovery for a genuinely unmatched case
still persists under that CourtListener identity.

A saved Scholar opinion records `source_provider: "google_scholar"` and
`retrieval_mode: "browser_clipboard"`, preserves its original `source_url`, and
becomes the preferred combined opinion of its CourtListener cluster when one
exists. The Python app—not the model—reads the regular clipboard and persists
through the shared validation/persistence service, which requires substantial
opinion text, a valid Scholar case URL, an official reporter citation
(California or `U.S.`), matching case identity, and qualifying reporter
markers. A mismatch,
snippet, stale clipboard, or missing markers performs no Library or Research
Cache write. No opinion or clipboard text is logged.

Validated external opinions receive conservative reader formatting: extracted
blocks are separated as paragraphs and recognized opinion headings are bold.
The original raw imported text remains durable. The reader names the actual
source from the preserved URL—for example,
`Source: Stanford Law School (scocal.stanford.edu)`—instead of presenting the
site merely as “External web.” Unknown qualifying sites are identified by their
hostname.

## Default-Browser Google Scholar Recovery

When a published California case still lacks qualifying official reporter
pagination after the deterministic cascade above, Open Law Lens can recover the
opinion through Google Scholar in the **current default HTTPS browser** using a
single deterministic, model-free sequence. This path never hardcodes Firefox,
Chrome, an app ID, an executable, or a profile: it resolves the default handler
through Gio at runtime and drives Linux Computer Use directly through a bounded
first-party MCP client (no Pi/model process and no `pi-mcp-adapter`).

Browser launch uses a bounded Gio helper with detached stdin/stdout/stderr, so
a cold-started browser cannot hold a piped CLI's JSON or stderr open after the
command finishes. Default HTTPS-handler selection is unchanged. When no
CourtListener cluster exists, the resolver preserves a supplied case name but
never treats a bare reporter citation as the expected Scholar case title.

The recovery-enabled extraction performs the baseline lookup, one deterministic
recovery attempt, import validation, and final re-extraction in one command:

```bash
uv run open-law-lens extract-case "11 Cal.5th 614" --recover-official
uv run open-law-lens extract-case "11 Cal.5th 614" --recover-official --find "beneficial relationship"
uv run open-law-lens extract-case --cluster-id 6240402 --recover-official
```

A focused diagnostics command uses the same service:

```bash
uv run open-law-lens recover-scholar "11 Cal.5th 614" \
  --citation "11 Cal.5th 614" --case-name "In re Caden C."
```

`open-scholar-browser` and `import-scholar-clipboard` remain available for
manual clipboard workflows. `import-scholar-clipboard` reads only the regular
clipboard (preferring `wl-paste`, falling back to `xclip`/`xsel`, capped at
8 MiB, never printing its contents), cleans browser/account chrome, requires an
exact official-citation match and qualifying official pagination, and persists
with `source_provider: google_scholar` and `retrieval_mode: browser_clipboard`.

The deterministic sequence scopes the exact target frame and selected tab,
classifies the selected document contextually, matches exactly one corroborated
result, and performs only targeted `Ctrl+A`/`Ctrl+C` key presses on an exact
numeric `window_id`. The bounded MCP
client exposes only `doctor`, `list_windows`, `get_app_state`, `perform_action`,
and `press_key`; screenshots, pointer coordinates, clicks, typing, scrolling,
dragging, setup operations, and every key other than `Ctrl+A`/`Ctrl+C` are
denied.

### Contextual barrier classification

Barrier detection never scans the whole document for bare trigger words.
Instead, a pure classifier (`classify_page`) inspects only the selected
document's own structure and returns one of `search_results`, `opinion`,
`challenge`, `no_results`, `missing_page`, or `unknown` with a stable reason
code. A challenge (CAPTCHA, robot check, unusual-traffic check, required
sign-in, consent interstitial) is recognized only through bounded, coherent
evidence — a challenge-specific page title, heading, short notice, or visible
modal containing a complete challenge phrase, paired with a required control
(a checkbox or challenge-labeled button) in the same verified frame. Ordinary
opinion prose, quotations, footnotes, headings like `CONSENT`, search-result
snippets, and the optional signed-out `Sign in` link can therefore never block
a recovery, even when they contain trigger words such as `consent` or `sign
in`. A genuine challenge overlay takes precedence and is always left visible
and untouched. An incomplete or unrecognized tree keeps polling within the
deadline and then reports a load/inspection failure — never a claim that no
official copy exists.

### Truthful outcomes

Recovery outcomes carry the failed `stage` and a stable `reason_code`
(for example `challenge_captcha`, `challenge_traffic`, `challenge_login`,
`challenge_consent`, `no_matching_result`, `ambiguous_results`,
`identity_mismatch`, `inspection_incomplete`, `page_load_timeout`,
`copy_failed`, `validation_rejected`, `persistence_failed`,
`reextract_failed`, `cancelled`, `busy`) through the recovery result, service
result JSON, CLI warnings, and GUI status. A single presentation mapping
drives both surfaces, and the GUI modal distinguishes **Scholar Access
Blocked** (a real challenge was detected), **Scholar Copy Rejected** (a
candidate was copied but failed validation), **Scholar Recovery Failed**
(load, inspection, copy, storage, or unexpected failure), **No Matching
Scholar Copy Found** (the bounded search genuinely found no qualifying
match — not a claim of global nonexistence), and concise cancellation/busy
status without a false not-found warning. The baseline reader remains offered
whenever it is available.

Recovery queries carry an explicit identity. When the official citation is
known, the Scholar search and the opened-opinion corroboration use that exact
citation, unchanged. When no official citation is known (for example a recent
slip opinion), the free-form query is never treated as a citation: recovery
requires the exact normalized case name plus a docket/case number (preferred)
or a filing year, and builds exactly one search as the quoted exact case name
plus that discriminator. Before the search, a California appellate case
number is enriched from trusted cluster fields and from URL-like fields of the
already-fetched raw opinion metadata (for example `F084030` from a
court's `download_url`); opinion text is never scanned, and enrichment
failure degrades to the filing-year path without a second search. The
selected result must be unique and corroborated from its own primary
reporter/court metadata — never from a snippet, the search box, or another
result: for citation-less recovery that metadata must parse as an official
California reporter citation (which excludes same-title same-year results
from other states, such as an `In re E.C.` Ohio decision), and must carry the
docket or, when the metadata omits the docket, the filing year. Two
qualifying results are never resolved by guessing. A narrowly bounded exception
handles docket-specific searches when CourtListener dates a later order rather
than the original published opinion: after verifying the exact quoted-name-plus-
docket search URL, one unique exact-title official-reporter candidate may be
opened despite a missing/different metadata year. It must then confirm the exact
docket in the opened front matter before copying; a year match cannot substitute.
Conflicting metadata dockets and ambiguous candidates still stop recovery.

Result parsing uses only the first primary metadata text node, excluding title
link descendants and subsequent snippets even without a leading ellipsis.
Opened front matter is traversed in document reading order, not Firefox's
breadth-first snapshot order, so nested caption/docket links are inspected before
the body within the existing 48-node/600-character bounds. The opened opinion is then
revalidated against the same identity from bounded front-matter text — exact
normalized title, the official citation selected from the result metadata,
and the docket when the identity carries one, otherwise the filing year — and
the import validator requires the copied opinion's derived citation to equal
the selected citation before any Library or Research Cache write. Missing
identity data returns `not_found` without opening a browser at all. The
existing import validator remains the final gate; missing identity,
ambiguity, mismatch, or failed validation performs no Library or Research
Cache write.

Run the read-only readiness check once per computer before the first desktop
recovery (do this on each machine after installation):

```bash
computer-use-linux doctor
```

If `can_build_accessibility_tree` or `can_query_windows` is `false`, run
`computer-use-linux setup` (and `computer-use-linux setup-window-targeting` on
GNOME Wayland, logging out and back in if prompted) and re-run `doctor`.

Recovery opens a **visible** default-browser window and leaves the browser open
on the imported opinion for transparency. If a CAPTCHA or robot check appears,
the command reports `blocked` and leaves the challenge visible rather than
attempting to solve it. A copied but invalid opinion is rejected without
touching the Library or Research Cache, and the CourtListener/slip baseline
remains available. The cross-process recovery lock is held from before the
browser job through clipboard capture, validation, and persistence, so a
concurrent recovery can never replace the clipboard mid-flight; around the
copy, the selected document and Scholar case URL are revalidated and the copy
target is confirmed to be document content rather than an editable
address/search field, failing safely otherwise. The clipboard read itself is
time- and size-bounded: a stalled reader is terminated at the deadline instead
of blocking forever. Cancellation is honored before persistence, and a
post-persistence Library readback failure reports that the copy was saved but
could not be re-verified — never not-found, and never a second search. External research writes to an isolated disposable cache —
under the private runtime workspace — so the next normal Open Law Lens launch
still shows your unchanged Research Cache sidebar, while validated official
opinions remain in the durable Library.

## Project Layout

- `open_law_lens/app.py`: GTK/Libadwaita app, reader, Research Cache, settings,
  and embedded Pi workflow.
- `open_law_lens/cli.py`: `open-law-lens` command dispatcher.
- `open_law_lens/authority_passages.py`: bounded verified opinion-passage
  extraction backing `extract-case --find`.
- `open_law_lens/client.py`: CourtListener API access and opinion extraction.
- `open_law_lens/cache.py`: disposable JSON cache layout and citation
  normalization.
- `open_law_lens/library.py`: durable SQLite library, display text, page
  markers, official-copy discovery outcomes, and Research Cache sets.
- `open_law_lens/config.py`: local settings, including the CourtListener token.
- `open_law_lens/pi_runtime.py`: Pi runtime discovery, authenticated model
  listing, effective default detection, and reasoning capability handling.
- `open_law_lens/fact_patterns.py`: ODT/PDF fact-pattern extraction for appeal
  issue assessment.
- `open_law_lens/quality.py`: official reporter citation and pagination quality
  checks.
- `open_law_lens/official_import.py`: shared external-opinion persistence
  service that preserves CourtListener cluster identity.
- `open_law_lens/computer_use_mcp.py`: bounded first-party stdio MCP client for
  the `computer-use-linux` MCP server; exposes only `doctor`, `list_windows`,
  `get_app_state`, `perform_action`, and `press_key`.
- `open_law_lens/browser_recovery.py`: deterministic default-browser Google
  Scholar recovery state machine (model-free, drives Computer Use directly,
  scopes the exact frame/tab, classifies the selected page contextually so
  challenge evidence is always paired and opinion prose never blocks, matches
  one corroborated result, copies with targeted `Ctrl+A`/`Ctrl+C`).
- `open_law_lens/scholar_recovery_service.py`: recovery-and-import service
  (recovery -> clipboard read -> validation -> persistence -> re-extraction)
  holding the cross-process recovery lock across the whole handoff and
  reporting typed stage/reason-code outcomes, used by the CLI, GTK app, and
  embedded legal-researcher sessions.
- `open_law_lens/scholar_browser.py`: default-browser Scholar launch and
  clipboard import primitives for recovery.
- `scripts/open-law-lens-agent-vte.sh`: embedded Pi terminal launcher. It keeps
  unrelated extensions disabled with `--no-extensions`; closed-corpus modes
  load only the passive sibling metrics observer, while research-capable modes
  also load the user-level `pi-web-access` extension.
- `.pi/settings.json`: project-local fallback Pi provider and model.
- `~/.pi/agent/npm/node_modules/pi-web-access/`: user-level web-access
  package explicitly loaded for research-capable Agent runs (or the equivalent
  path under `PI_CODING_AGENT_DIR`).
- `.pi/skills/legal-researcher/SKILL.md`: Pi legal-research workflow,
  web-search fallback rules, and the pre-answer legal-source audit. The
  launcher preloads this file into the system prompt for research modes.

## Local Files and Credentials

Do not commit local runtime data:

- `config.json`: local settings and CourtListener token.
- `cache/`: disposable CourtListener lookup and import cache.
- `library/`: durable local SQLite authority library.
- `.pi/npm/`: optional project-local Pi package cache; the embedded workflow
  uses the user-level Pi package installation instead.
- `.venv/`, `__pycache__/`, `.pytest_cache/`, and `.mypy_cache/`: generated
  development artifacts.

These paths are ignored by Git in this repository.

## Prior Brief quality and search coverage

Prior Brief answers recommend documents, not independently verified current law.
The revised default ranks direct briefing first, attributes advocacy, distinguishes
child/adult/nondependent contexts and trial burdens from appellate review, requires
complete selected-source inspection, and limits exact linked quotes to 2–10 words.
Temporary extractions are permitted only inside the disposable agent workspace.
Searches should be short and gap-driven; `--match any` ORs individual tokens,
including split citation numbers. Prefer `all` or a specific `phrase` search.

`search-briefs` retains its existing results and returned `count`, adding the
effective `limit` (clamped to 1–100) and `has_more`. An extra query row determines
coverage without being returned. `has_more: false` means all matches **for that
query**, not all relevant archive documents. No automatic pagination, reindexing,
ranking change, or schema migration is involved. Python callers can use
`PriorBriefLibrary.search_page()`; `search()` still returns the same list shape.

Only an exact known shipped Prior Brief default (including normalized legacy CLI
prefixes) upgrades in memory on configuration load. Customized prompts and all
model/reasoning profiles survive; no deployment step rewrites `config.json`.
Normal user-initiated Settings saves behave as before. Reload application code
and launch a new Agent session to receive revised defaults; existing sessions
are unchanged. Prompt requirements are not runtime enforcement: see
[Prior Brief acceptance results](docs/prior-brief-quality-acceptance.md) for
observed behavioral failures and validation limits.

## General Law quality validation

The preloaded skill remains the single workflow authority. It requires
issue-specific, gap-driven research, independent verification of statutory
incorporation steps, explicit treatment of adverse passages and amendments,
and separation of express text/holdings from analogy and proposed inference.
The mandatory published-case floor and single Scholar recovery remain intact.
No model profile, launch interface, database schema, or private setting changes
are required. Newly launched Agent sessions receive the updated skill; existing
sessions do not. See [acceptance results](docs/general-law-quality-acceptance.md)
for checks performed and remaining quality/efficiency validation.

## Tests

Run the unit tests:

```bash
uv run python -m unittest discover -s tests
```

Run a quick syntax check:

```bash
uv run python -m py_compile open_law_lens/*.py
```

Check Markdown and whitespace-sensitive diffs before committing:

```bash
git diff --check
```

# Open Law Lens

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
- Research Cache sidebar for the authorities currently in view.
- Durable SQLite library at `library/open_law_lens.sqlite3` for saved authority
  data, display text, and reporter page-marker metadata.
- Disposable JSON API cache under `cache/`.
- Subsequent-treatment agent workflow using Open Law Lens CLI citation-graph leads.
- Deterministic CourtListener, California Courts, Google Scholar, and Tavily
  fallback flow for official reporter text and pagination gaps.
- Reader links for cited cases, statutes, and rules.
- Named Research Cache sets.
- Exact-phrase search across the indexed prior-brief archive, with newest-first
  reader navigation through matches.
- Selected-text launcher through `open-law-lens open-selected`.
- Embedded Pi-only Agent workflow for legal research questions, selected-cache
  questions, and appellate issue assessment.
- Appeal issue assessment from a current-case SOCF or another ODT/PDF fact
  pattern, with configurable issue presets and custom claims.

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
and `~/.pi/web-search.json` credentials as ordinary Pi sessions. The launcher
also uses the Node runtime installed alongside Pi instead of the desktop
session's system Node.

The Settings window lists the models currently authorized in Pi and lets each
user choose a separate model and reasoning effort for Query Law, Query Research
Cache, Query Prior Briefs, and Assess Argument. These personal overrides are
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
uv run open-law-lens case-search "beneficial relationship exception"
uv run open-law-lens extract-statute "Welf. & Inst. Code, § 300"
uv run open-law-lens extract-rule "Cal. Rules of Court, rule 8.1115"
uv run open-law-lens published-citing-cases --cluster-id 6240402 --limit 10 --json
```

`extract-case` automatically attempts to resolve qualifying official reporter
pagination. Its JSON includes `official_pagination` and
`pagination_marker_count`; use `--refresh` to bypass saved lookup data and the
24-hour Tavily discovery-outcome cache:

```bash
uv run open-law-lens extract-case "20 Cal.4th 1135" --refresh
```

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
- Appeal Issue Assessment: assess a proposed appellate claim against an ODT or
  PDF fact pattern. The app extracts the fact pattern into a temporary
  workspace, launches Pi in Appeal mode, and directs it to research
  California law through Open Law Lens CLI commands.

The separate **Search Briefs** scope performs a local, non-LLM exact-phrase
search. It opens matching briefs newest-first in the main reader without adding
them to the Research Cache. Use `Ctrl+S` to activate this mode, then `Ctrl+G`
and `Ctrl+Shift+G` to move forward and backward through occurrences across
matching briefs.

Agent runtime settings, including the four per-query Pi model/reasoning
profiles, prompt templates, appeal issue presets, and fact-pattern source, are
available in the app Settings window. Subsequent Treatment uses the Query Law
profile. **Search Briefs** is local and does not launch Pi.

Law, Subsequent Treatment, and Appeal runs explicitly load the legal-researcher
skill and the user-level `pi-web-access` extension. Agents should use the
enhanced `extract-case` command first; Pi's `web_search` remains available only
for unresolved, open-ended verification after that command's deterministic
fallbacks. This agent-facing web search is separate from the native Python
Tavily resolver described below. Research Cache and Prior Brief runs disable
skills and the web extension and remain closed-corpus workflows.

All embedded runs additionally load the trusted, capture-only PiPlanner
extension from `${XDG_DATA_HOME:-~/.local/share}/pi-planner/package/src/run-review-capture.ts`
(override with `PI_PLANNER_REVIEW_CAPTURE_EXTENSION`) when it is installed.
It registers no tools and does not broaden Agent capabilities; it snapshots the
completed run (active branch only, no environment values or credentials) for
independent `/review-run` audits in a normal coding Pi session. If it is
absent, the Agent still launches normally with a concise stderr warning.

Pi remains in a private disposable workspace rather than using the source tree
as its working directory. Agent-facing Open Law Lens commands explicitly select
the installed project with this canonical prefix:
`uv run --project "$OPEN_LAW_LENS_PROJECT_DIR" --no-sync open-law-lens ...`.
This keeps command resolution deterministic without exposing the project tree
through ordinary workspace discovery.

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
across app launches. Appeal Issue Assessment always includes its selected fact
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

## Appeal Issue Assessment

The Appeal Issue Assessment workflow is for quickly testing possible appellate
claims against a fact pattern. It is available from the visible **Assess
Argument…** menu in the Research composer heading. The menu includes assessment
actions for configured argument presets, a custom assessment action, and a
shortcut to edit the appeal argument settings.

By default, Open Law Lens tries to use the SOCF ODT for the currently selected
case. The Settings window can point the workflow at a different fact-pattern
ODT or PDF. ODT files are read directly; PDF extraction uses the system
`pdftotext` command.

When an assessment starts, the app copies the source fact pattern into a
temporary agent workspace, writes an extracted text file, and launches Pi in
the embedded terminal. The default assessment prompt asks Pi to analyze
preservation, standard of review, factual support, governing law, prejudice,
and likely respondent arguments. It treats every selected fact pattern as the
complete factual record and prohibits speculation about a more complete record
or a generic record-completeness caveat. A concrete ambiguity, contradiction,
or missing record citation in the supplied text may still be addressed where
it affects the analysis. The prompt also requires a final rating line:

```text
Rating: Strong, Medium, Weak, or Frivolous
```

The workflow is intentionally research-oriented. Pi is directed to use
Open Law Lens CLI commands such as `case-search`, `extract-case`,
`extract-statute`, and `extract-rule` before relying on authority.

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

## Official-Pagination Fallback

CourtListener and the durable Library remain the primary case sources. Entering
a citation in the GUI, running `extract-case` (including `--cluster-id`), or
using `extract` for a detected case invokes the same resolver. When a published
California case lacks qualifying official reporter page markers, the resolver
uses this sequence:

1. Durable Library and CourtListener.
2. The California Courts slip-opinion display fallback when applicable.
3. Direct Google Scholar lookup.
4. One native Tavily discovery pass.
5. The best readable CourtListener or slip text, with an explicit pagination
   warning, if no qualifying reporter copy is found.

Tavily is skipped after an earlier source supplies qualifying official
pagination and for known unpublished cases. JSON reports
`official_pagination` and `pagination_marker_count`; usable unpaginated text may
still return `ok: true` with warnings.

The native client makes one Tavily `basic` request per unresolved identity,
requests at most 10 results and Markdown raw content, and preserves Tavily's
result order while de-duplicating URLs. Tavily is discovery only: Open Law Lens
ignores synthesized answers and snippets. It is not a Pi Agent session and does
not open the embedded Pi terminal.

Open Law Lens fetches each original public HTTPS URL itself and validates the
case identity, exact official citation, substantial opinion text, and reporter
page markers before writing anything. Candidate fetching rejects URL
credentials and private, loopback, link-local, or reserved destinations and
revalidates every redirect. If direct retrieval is blocked or unusable, Tavily
Markdown `raw_content` may be validated as a fallback. Any public HTTPS site may
qualify; Stanford and Justia are useful sources, not an allowlist.

A saved opinion keeps the original `source_url` and records
`source_provider: "external_web"`, `retrieval_provider: "tavily"`, and
`retrieval_mode: "direct"` or `"tavily_raw"`. If CourtListener already supplied
a cluster, the imported copy becomes its preferred combined opinion while the
CourtListener cluster ID and citation-graph metadata are preserved. This avoids
duplicate cases and prevents parallel-reporter pagination from being mixed with
the validated official copy. Search answers, credentials, and failed candidate
bodies are never stored as authority.

Native Tavily access shares Pi Web Access configuration; Open Law Lens does not
have a separate API-key setting. Configuration is discovered at
`PI_CODING_AGENT_DIR/web-search.json`, otherwise
`$XDG_CONFIG_HOME/pi/web-search.json`, otherwise `~/.pi/web-search.json`.
`TAVILY_API_KEY`, literal `tavilyApiKey` values, `$NAME`/`${NAME}` references,
escaped `$`/`!` literals, and trusted `!command` credential sources use Pi Web
Access semantics.

A durable SQLite outcome cache prevents repeated Tavily requests for the same
unresolved identity for 24 hours. Missing credentials, authentication failures,
and transient network failures are not cached. `extract-case --refresh`
bypasses and replaces a cached discovery outcome. In the reader, **Find
paginated copy** forces a fresh Scholar/Tavily retry and is hidden once a
qualifying copy loads. If the retry still fails, **Find Paginated Copy** lists
candidate URLs and concise rejection reasons while retaining browser, URL-fetch,
clipboard, and manual-import controls. Manual imports pass the same citation and
pagination quality gate.

Validated external opinions receive conservative reader formatting: extracted
blocks are separated as paragraphs and recognized opinion headings are bold.
The original raw imported text remains durable. The reader names the actual
source from the preserved URL—for example,
`Source: Stanford Law School (scocal.stanford.edu)`—instead of presenting the
site merely as “External web.” Unknown qualifying sites are identified by their
hostname.

## Project Layout

- `open_law_lens/app.py`: GTK/Libadwaita app, reader, Research Cache, settings,
  and embedded Pi workflow.
- `open_law_lens/cli.py`: `open-law-lens` command dispatcher.
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
- `open_law_lens/official_copy.py`: deterministic Tavily discovery, identity
  validation, outcome caching, and resolver results.
- `open_law_lens/official_import.py`: shared Scholar, Tavily, URL, and clipboard
  persistence service that preserves CourtListener cluster identity.
- `open_law_lens/tavily.py`: native dependency-free Tavily client and shared Pi
  credential resolution.
- `scripts/open-law-lens-agent-vte.sh`: embedded Pi terminal launcher. Alongside
  `--no-extensions` isolation (and `pi-web-access` in research modes) it
  explicitly loads the capture-only PiPlanner extension when installed; the
  extension registers no tools and exports `PI_PLANNER_REVIEW_CAPTURE_APP=open-law-lens`,
  the current mode as `PI_PLANNER_REVIEW_CAPTURE_WORKFLOW`, and the project root.
- `.pi/settings.json`: project-local fallback Pi provider and model.
- `~/.pi/agent/npm/node_modules/pi-web-access/`: user-level web-access
  package explicitly loaded for research-capable Agent runs (or the equivalent
  path under `PI_CODING_AGENT_DIR`).
- `.pi/skills/legal-researcher/SKILL.md`: Pi legal-research workflow and
  web-search fallback rules.

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

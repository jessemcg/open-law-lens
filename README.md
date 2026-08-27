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
- CourtListener-first baseline with a single confined default-browser Google
  Scholar recovery for official reporter text and pagination gaps.
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
uv run open-law-lens extract-case "13 Cal.4th 952" --find "presumed father"
uv run open-law-lens case-search "beneficial relationship exception"
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
matched query names, and nearest preceding reporter page marker:

```bash
uv run open-law-lens extract-case "13 Cal.4th 952" --find "presumed father" --find "biological father"
```

`--find` is mutually exclusive with `--text`. Passing no `--find` keeps the
ordinary full-JSON `extract-case` output unchanged.

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

Law, Subsequent Treatment, and Appeal runs are research-capable. The launcher
preloads the tracked legal-researcher skill into the disposable workspace's
system prompt once (instead of passing `--skill` and spending a model turn
reading the file), keeps `--no-skills` so no other skills load, and loads the
user-level `pi-web-access` extension. Agents route by source through an
explicit gate in that skill. There is a narrow enactment-only exception,
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
`case-search --limit 5` is run only when no reliable citation or name is
already known. Pi's `web_search` remains available only for unresolved,
open-ended verification after those deterministic fallbacks. This agent-facing
web search is separate from the confined default-browser Scholar official-copy
recovery described below, and is never used to retrieve an official reporter
copy. Research Cache and Prior Brief runs load no skill and no web extension
and remain closed-corpus workflows.

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
Open Law Lens CLI commands such as `extract-statute`, `extract-rule`,
`extract-case` (including `extract-case --find` for narrow propositions),
and focused `case-search` before relying on authority.

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

A saved Scholar opinion records `source_provider: "google_scholar"` and
`retrieval_mode: "browser_clipboard"`, preserves its original `source_url`, and
becomes the preferred combined opinion of its CourtListener cluster when one
exists. The Python app—not the model—reads the regular clipboard and persists
through the shared validation/persistence service, which requires substantial
opinion text, a valid Scholar case URL, an official California reporter
citation, matching case identity, and qualifying reporter markers. A mismatch,
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
matches exactly one corroborated result, and performs only targeted
`Ctrl+A`/`Ctrl+C` key presses on an exact numeric `window_id`. The bounded MCP
client exposes only `doctor`, `list_windows`, `get_app_state`, `perform_action`,
and `press_key`; screenshots, pointer coordinates, clicks, typing, scrolling,
dragging, setup operations, and every key other than `Ctrl+A`/`Ctrl+C` are
denied.

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
remains available. External research writes to an isolated disposable cache —
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
  scopes the exact frame/tab, matches one corroborated result, copies with
  targeted `Ctrl+A`/`Ctrl+C`).
- `open_law_lens/scholar_recovery_service.py`: recovery-and-import service
  (recovery -> clipboard read -> validation -> persistence -> re-extraction),
  used by the CLI, GTK app, and embedded legal-researcher sessions.
- `open_law_lens/scholar_browser.py`: default-browser Scholar launch and
  clipboard import primitives for recovery.
- `scripts/open-law-lens-agent-vte.sh`: embedded Pi terminal launcher. It keeps
  unrelated extensions disabled with `--no-extensions`; closed-corpus modes
  load no extension, while research-capable modes load only the user-level
  `pi-web-access` extension.
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

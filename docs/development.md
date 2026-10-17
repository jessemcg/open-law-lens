# Development

Public installations are complete editable source checkouts. See
[source-install.md](source-install.md#development-helper) for the receipt-bound
`env check/sync/run` helper. Launch never provisions. GPL v3 is in [LICENSE](../LICENSE).

## Jesse's maintained workflow

This is separate from public installation; never adopt or relocate its environment.
Use the absolute UvEnvironments helper, for example:

```bash
P=/absolute/path/to/UvEnvironments/project-env
"$P" --project /tmp/oll-source --environment /tmp/oll-env sync OpenLawLens
"$P" --project /tmp/oll-source --environment /tmp/oll-env run OpenLawLens python -m unittest discover -s tests
```

Always use paired disposable source/environment overrides for write-producing
checks. Copy tracked source and intentional new files only, never private config,
library/cache, sessions or environments. Same-environment children use
`sys.executable`; cross-project calls select the callee helper. Source edits need
no sync; dependency-contract or source-location changes require explicit sync.

## Checks

Run `python -m unittest discover -s tests` in the isolated environment. Compile
source strings with `compile()` to avoid bytecode in the maintained checkout;
run `bash -n` on shell resources and `git diff --check`. Installer tests are
stdlib unittest fixtures and never provision the host or use real credentials.
See [current installer results](source-install-validation.md),
[portability results](portability-validation.md), and focused acceptance documents
linked from [user-guide.md](user-guide.md).

## Project Layout

- `open_law_lens/app.py`: GTK/Libadwaita app, reader, Research Cache, settings,
  and embedded Pi workflow.
- `open_law_lens/agent_followup.py`: GTK-independent client and protocol types
  for the bounded Unix-socket follow-up bridge, with typed busy/unavailable/
  uncertain/protocol failures and application-owned runtime cleanup.
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
  load only the passive sibling metrics observer and the app-owned follow-up
  bridge, while research-capable modes also load the user-level
  `pi-web-access` extension.
- `.pi/extensions/open-law-lens-followup-bridge.ts`: the explicitly staged,
  non-model-facing live follow-up bridge; registers no tools.
- `.pi/settings.json`: maintained-only fallback; public mode ignores it.
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

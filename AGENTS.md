# Repository Guidelines

## Project Structure & Module Organization
- `open_law_lens/` is the Python package.
- `open_law_lens/app.py` is the GTK/Libadwaita desktop app, including the citation lookup UI, cached-case browser, opinion reader, settings dialog, and embedded Pi terminal workflow.
- `open_law_lens/cli.py` defines the `open-law-lens` command. Keep GUI and CLI behavior routed through this module rather than adding ad hoc entry scripts.
- `open_law_lens/authority_passages.py` owns bounded, verified `extract-case --find` passage output and must never re-introduce the full opinion text it exists to omit.
- `open_law_lens/client.py` owns CourtListener API access and opinion-text extraction.
- `open_law_lens/cache.py` owns local JSON cache layout and citation normalization.
- `open_law_lens/library.py` owns the durable SQLite case library, display-text extraction, reporter page-marker offsets, and official-copy outcome cache.
- `open_law_lens/official_import.py` is the single external-opinion persistence service. `open_law_lens/authority_resolver.py` supplies the CourtListener/slip baseline and never performs direct HTTP Scholar or Tavily discovery.
- `open_law_lens/browser_recovery.py` owns the deterministic default-browser Google Scholar recovery state machine. It drives Linux Computer Use directly through the first-party `ComputerUseMCPClient` (no Pi, model, or `pi-mcp-adapter`), acquires a cross-process recovery lock, scopes the exact target frame/tab, matches exactly one corroborated result, and performs only targeted `perform_action`/`Ctrl+A`/`Ctrl+C` mutations. Native Tavily discovery (`tavily.py`) and `official_copy.py` were removed; their opinions are deleted by a one-time library migration.
- `open_law_lens/computer_use_mcp.py` is the bounded first-party stdio MCP client for the `computer-use-linux` MCP server. It exposes only `doctor`, `list_windows`, `focused_window`, `get_app_state`, `perform_action`, `press_key`, and exact-ID `activate_window`, and rejects screenshots, coordinates, clicks, typing, scrolling, dragging, setup operations, broad app-identity targeting, and every key except targeted `Ctrl+A`/`Ctrl+C`.
- `open_law_lens/scholar_recovery_service.py` owns the recovery-and-import flow: deterministic browser recovery -> regular clipboard read -> existing Scholar cleanup/validation -> `persist_official_opinion` -> Library re-extraction -> a typed final result. It is used by the CLI (`--recover-official` and `recover-scholar`), the GTK app, and embedded legal-researcher sessions.
- `open_law_lens/config.py` owns local settings, including the CourtListener token and the default agent prompt templates.
- `open_law_lens/pi_runtime.py` owns Pi runtime discovery, authenticated model enumeration, and atomic updates to the project Pi model setting.
- `open_law_lens/agent_commands.py` owns the canonical workspace-safe Open Law Lens command prefix used in agent prompts and CLI suggestions.
- `scripts/open-law-lens-agent-vte.sh` launches Pi from the embedded terminal. It must use the Node runtime shipped beside the selected Pi executable so desktop PATH differences cannot fall back to an incompatible system Node. It also resolves `uv` deterministically (validated `OPEN_LAW_LENS_UV_BIN`, `uv` on `PATH`, then `$HOME/.local/bin/uv`), prepends the resolved directory to `PATH`, and fails before any model work if `uv` is unresolvable. Preserve its temporary-workspace and cache-directory behavior unless the task explicitly changes agent launch semantics.
- Research-capable embedded Agent runs explicitly load the user-level `pi-web-access` package from Pi's agent directory while `--no-extensions` keeps unrelated extensions disabled. Do not vendor extension source or install it under the project's `.pi/npm/` directory.
- `.pi/SYSTEM.md` is the replacement legal-knowledge-work prompt copied into every private embedded Pi workspace and passed explicitly at launch. For research-capable modes the wrapper appends the tracked `.pi/skills/legal-researcher/SKILL.md` contents to this copy once, so Pi must not need to spend a turn reading the skill file.
- `.pi/skills/legal-researcher/SKILL.md` is the single source of truth for the legal-research routing rule, and that rule is a repository invariant. The skill routes every question through exactly two paths: a narrow enactment-only exception reserved for requests that remain entirely textual (current text/citation/effective-date and no more), and a mandatory enactment-plus-case route for any definition or explanation of a legal status, doctrine, test, standard, or term of art and for scope, application, biology, burdens, rebuttal, conflicts, exceptions, rights, duties, or practical consequences. A "simple what is" question shortens the answer but never waives this case floor. Future efficiency work must not weaken this explicit gate back into a discretionary "ask whether"; if so" recommendation, must not let legal-status questions cite no case, and must keep the bounded direct `--find` extraction and same-round parallelism preferred over broad `case-search` discovery. Do not duplicate the full routing workflow in `.pi/SYSTEM.md` or the General Law prompt template; the preloaded skill remains authoritative.
- `open-law-lens-icon.png` is the project icon used by the desktop launcher.
- `pyproject.toml` and `uv.lock` define the Python 3.13 uv environment. Keep them synchronized when changing dependencies.

## Build, Test, and Development Commands
- `uv sync`: install dependencies into the project-managed environment.
- `uv run open-law-lens app`: launch the GTK app.
- `uv run open-law-lens lookup-citation "576 U.S. 644"`: exercise the citation lookup CLI.
- `uv run open-law-lens show-library`: inspect saved library cases.
- `uv run open-law-lens show-cache`: inspect Research Cache cases listed in the sidebar.
- `uv run open-law-lens library-db`: print the durable SQLite library path.
- `uv run open-law-lens clear-cache`: clear only Research Cache data.
- `uv run python -m unittest discover -s tests`: run the test suite.
- `uv run python -m py_compile open_law_lens/*.py`: quick syntax/import-adjacent check for package modules.
- `git diff --check`: check whitespace before committing.

## Coding Style & Naming Conventions
- Python 3.13+ only.
- Follow PEP 8: 4-space indentation, `snake_case` for functions and variables, `PascalCase` for classes, uppercase constants.
- Prefer small modules with clear boundaries: UI in `app.py`, API calls in `client.py`, disposable JSON cache logic in `cache.py`, durable library logic in `library.py`, user config in `config.py`.
- Keep GTK/Libadwaita changes consistent with the existing quiet utility-app style. Use modern Adwaita widgets where the app already uses them.
- Preserve type hints on public helpers and callbacks; add focused tests when changing parsing, caching, config, or CLI behavior.

## Testing Guidelines
- Use `uv run python -m unittest` for normal validation.
- For library, cache, config, and client changes, add or update tests under `tests/` using `unittest` unless the project intentionally migrates to another test runner.
- For CourtListener API changes, keep tests network-free by using cached fixtures, temporary directories, or mocks. Do not make routine tests depend on live network access or real credentials.
- For GUI changes, run the app when a display is available and manually exercise the affected flow: citation lookup, cached-case selection, opinion text display, settings save/load, and embedded Pi agent launch if touched.
- When sandbox-only checks cannot reproduce a reported desktop/runtime issue, perform appropriate live host testing outside the sandbox after approval: verify running Open Law Lens processes, active launcher/cache paths, and the exact user-facing workflow before declaring the issue fixed.

## Configuration, Cache, and Security Notes
- `config.json` is local runtime state and may contain a CourtListener token. Do not commit it.
- `library/` contains the durable SQLite case library. It stores raw CourtListener JSON plus display-ready text and page-marker metadata. Do not commit it.
- `cache/` contains disposable local CourtListener lookup, cluster, opinion, and case-index data. Do not commit generated cache data unless a task explicitly asks for a fixture, and then place it under an intentional test fixture path.
- The app sidebar is the Research Cache, not the full library. Clearing Research Cache should hide sidebar cases while preserving the durable library database.
- `.venv/`, `__pycache__/`, `.pytest_cache/`, and `.mypy_cache/` are generated and should stay out of diffs.
- `.pi/npm/` is Pi's generated project-local package cache. The embedded workflow uses Pi's user-level package installation instead, so this directory should stay out of diffs.
- Prefer `OPEN_LAW_LENS_CACHE_DIR` for isolated test or smoke-run caches instead of using or clearing the user’s default cache.
- Prefer `OPEN_LAW_LENS_LIBRARY_DB` for isolated tests or experiments that should not touch the user’s durable library.
- `COURTLISTENER_TOKEN` may be used by the app/client, but credentials should remain in environment variables or local config only.
- Deterministic Scholar recovery drives Linux Computer Use directly through the bounded `ComputerUseMCPClient`; it never launches a Pi/model process, never exposes `bash`/filesystem/`web_search`, and never logs opinion, clipboard, or accessibility-tree text. Embedded legal-researcher agents merely invoke `extract-case --recover-official` and rely on the command's final result rather than orchestrating the desktop.

## Desktop Launcher Notes
- Shared desktop files live outside this repo in `/home/jesse/Dropbox/MCGLAW/config_files/Desktop_Files`.
- The current launcher pair is `com.mcglaw.OpenLawLens.desktop` and `launch-open-law-lens.sh`.
- Keep the launcher pointing at `uv run --project /home/jesse/Dropbox/MCGLAW/config_files/scripts/PROJECTS/OpenLawLens open-law-lens app` unless the package entry point changes.
- If launcher behavior changes, validate the desktop file with `desktop-file-validate` and the script with `bash -n`.

## Commit & Pull Request Guidelines
- Use concise, imperative commit subjects, for example `Add cache refresh option`.
- Keep one logical change per commit. Separate source changes from shared `Desktop_Files` commits because that directory is a separate repository.
- Call out dependency, config, cache-layout, and desktop-launcher changes explicitly in PR or commit notes.

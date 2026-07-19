# Repository Guidelines

## Project Structure & Module Organization
- `open_law_lens/` is the Python package.
- `open_law_lens/app.py` is the GTK/Libadwaita desktop app, including the citation lookup UI, cached-case browser, opinion reader, settings dialog, and embedded Pi terminal workflow.
- `open_law_lens/cli.py` defines the `open-law-lens` command. Keep GUI and CLI behavior routed through this module rather than adding ad hoc entry scripts.
- `open_law_lens/client.py` owns CourtListener API access and opinion-text extraction.
- `open_law_lens/cache.py` owns local JSON cache layout and citation normalization.
- `open_law_lens/library.py` owns the durable SQLite case library, display-text extraction, and reporter page-marker offsets.
- `open_law_lens/config.py` owns local settings, including the CourtListener token.
- `open_law_lens/pi_runtime.py` owns Pi runtime discovery, authenticated model enumeration, and atomic updates to the project Pi model setting.
- `scripts/open-law-lens-agent-vte.sh` launches Pi from the embedded terminal. It must use the Node runtime shipped beside the selected Pi executable so desktop PATH differences cannot fall back to an incompatible system Node. Preserve its temporary-workspace and cache-directory behavior unless the task explicitly changes agent launch semantics.
- `.pi/extensions/pi-web-search/` contains the pinned web-search extension bundled for the embedded Pi workflow. Do not replace it with a machine-local `.pi/npm/` dependency.
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
- `.pi/npm/` is Pi's generated project-local package cache. It is not required by the bundled extension and should stay out of diffs.
- Prefer `OPEN_LAW_LENS_CACHE_DIR` for isolated test or smoke-run caches instead of using or clearing the user’s default cache.
- Prefer `OPEN_LAW_LENS_LIBRARY_DB` for isolated tests or experiments that should not touch the user’s durable library.
- `COURTLISTENER_TOKEN` may be used by the app/client, but credentials should remain in environment variables or local config only.

## Desktop Launcher Notes
- Shared desktop files live outside this repo in `/home/jesse/Dropbox/MCGLAW/config_files/Desktop_Files`.
- The current launcher pair is `com.mcglaw.OpenLawLens.desktop` and `launch-open-law-lens.sh`.
- Keep the launcher pointing at `uv run --project /home/jesse/Dropbox/MCGLAW/config_files/scripts/PROJECTS/OpenLawLens open-law-lens app` unless the package entry point changes.
- If launcher behavior changes, validate the desktop file with `desktop-file-validate` and the script with `bash -n`.

## Commit & Pull Request Guidelines
- Use concise, imperative commit subjects, for example `Add cache refresh option`.
- Keep one logical change per commit. Separate source changes from shared `Desktop_Files` commits because that directory is a separate repository.
- Call out dependency, config, cache-layout, and desktop-launcher changes explicitly in PR or commit notes.

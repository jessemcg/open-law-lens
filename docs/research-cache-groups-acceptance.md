# Research Cache groups — acceptance (2026-09-11)

## Scope

Presentation only: Statutes (including rules), Case Law, Prior Briefing, Saved
Answers. Empty groups are omitted; counts come from rendered typed rows. Existing
within-group timestamp/tie-break keys, storage, callbacks, and Research Sets are
unchanged. Category CSS is restricted to `list.research-cache`, excluding the
pinned Current Case list. No launcher, CLI, dependency, or storage migration.

## Automated verification

- `uv run python -m unittest discover -s tests`: **995 passed**.
- `ADW_DEBUG_HIGH_CONTRAST=1 uv run python -m unittest discover -s tests -p test_research_cache_sidebar.py`: **7 passed**.
- Package and preview/test `py_compile`: passed.
- `git diff --check`: passed.
- Logs: `/tmp/oll-cache-final-suite.log`, `/tmp/oll-cache-hc-tests.log`.

The real-GTK sidebar tests cover all five stored types, four groups, counts from
rendered rather than raw indexed items, empty/single/mixed groups, last-item
removal followed by rebuild, explicit selection, first selectable row, inert
headers, timestamp boundaries/ties, typed remove callbacks/checkmarks, temporary
Research Set round-trip without dirtying, CSS parsing, and appearance changes
without row reconstruction or selection loss. Existing full-suite tests cover
reader payloads and removal behavior. The new action-rail test mocks remove
handlers rather than claiming to exercise their full persistence implementation.

## Isolated desktop evidence

`tests/preview_research_cache.py` creates a fresh `/tmp/oll-cache-preview-*` root,
redirects config/cache/library/brief-index paths, blocks socket connections,
disables Current Case discovery/background suggestions, and uses a separate
NON_UNIQUE application identity. It never launches an agent. Jesse's existing
Open Law Lens process (11837) remained running and was not targeted.

Screenshots were observed through Linux Computer Use in this session (not saved
as repository assets):

| Preview | Window | Observation |
| --- | --- | --- |
| Original `HEAD` app with same synthetic seed | 2947867002 | Before: shared Authorities grouping, followed by Prior Briefing and Saved Answers. |
| Updated app | 2947867001, 2947867003 | After: Statutes **2**, Case Law **1**, Prior Briefing **1**, Saved Answers **1**; rules included under Statutes; action rail retained. Light and dark heading bands/leading borders visible. |
| Updated stress data | 2947867003 | 105 additional long statute titles wrap; action columns remain aligned in the scrollable sidebar. F10 restored the saved five-item set and asserted clean metadata. |
| Actual Libadwaita high contrast | 2947867007 | `get_high_contrast()` and the list's HC class asserted true. Neutral outlined bands, legible labels/counts, leading borders and remove icons visible. |

AT-SPI exposed heading text/counts with headers neither focusable nor selectable,
and typed checkbox descriptions for each item category. The pinned Current Case
remained outside category styling. Preview windows were closed; their processes
were verified gone. Logs include `/tmp/oll-cache-final-preview.log` and
`/tmp/oll-cache-hc-preview.log`.

Limits: an initial process-local GTK HighContrast theme switch did **not** set
Libadwaita's HC state; that attempt is not an HC pass. The helper now uses the
startup `ADW_DEBUG_HIGH_CONTRAST=1` override instead. Pointer/focus observations
were inconsistent on this scaled multi-monitor desktop, so the exploratory
pointer actions are **not** claimed as end-to-end activation/removal acceptance.
Those contracts are covered by automated tests. No numeric pixel contrast audit
or screen-reader speech test was performed. Some early screenshot crops included
surrounding windows; these are not exported as evidence assets.

## Reproduce safely

```sh
uv run python tests/preview_research_cache.py
ADW_DEBUG_HIGH_CONTRAST=1 uv run python tests/preview_research_cache.py
```

F6/F7 change only the preview's light/dark preference and assert row identity and
selection retention. F9 seeds stress data; F10 reloads the synthetic saved set.
For before/after comparison, set `OLL_PREVIEW_BEFORE` to a temporary original app
module obtained with `git show <baseline>:open_law_lens/app.py`. Do not use real
cache/config paths or the normal app identity for acceptance.

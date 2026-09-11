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

## Stronger category styling follow-up (2026-09-11)

The existing palette is unchanged. Light ordinary/header/hover/selected fills
are 10/21/16/23%; dark fills are 16/30/23/31%. Category edges are 4px.
Selected rows retain a neutral 1px inset outline at 65% foreground; keyboard
focus takes precedence with a 2px outline. Subtitles use 85% neutral foreground
with widget opacity 1, exclusively inside Research Cache. Selected hover and
backdrop retain the selected fill and outline. All new selectors are scoped to
`list.research-cache`; pinned Current Case and reader CSS are unchanged.
At Jesse's follow-up request, removed the Statutes “Includes rules of court”
subheading; rules still belong to Statutes and contribute to its count.

### Composited contrast audit

The sidebar test loads the full application stylesheet on GTK 4.14 / Libadwaita
1.5. It renders actual theme/window/list/row backgrounds into Cairo, composites
computed foreground colors and subtitle alpha, and evaluates WCAG relative
luminance. It checks all four categories, headings, ordinary/hover/selected,
selected-hover/backdrop, focused-selected-hover and focused-unselected rows in
light and dark, then repeats with actual Libadwaita high contrast enabled.
GTK snapshot-rendered outline widths/colors, category edges, revealed remove
controls, and checked/unchecked checkbox boundaries are tested. Checkbox
boundaries are compared against both the row and checkbox interior. A separate
pinned list remains untinted even when deliberately given a category class.

| Mode | Minimum primary text | Minimum subtitle | Minimum tested state/control indicator |
| --- | ---: | ---: | ---: |
| Normal light + dark | 7.043:1 | 5.252:1 | 3.029:1 |
| Actual HC light + dark | 4.515:1 | 4.515:1 | 4.515:1 |

Two bounded neutral accessibility adjustments were needed:
- Libadwaita draws checkbox boundaries using shadows. A scoped 68% neutral inset
  shadow is the first whole-percent opacity passing 3:1 against both backgrounds
  (65–67% failed); the requested selected-row outline remains at 65%.
- The local HC theme's white/selected-blue pairing measured only 3.77:1.
  Mixing its selected background with 10% black produces 4.515:1. HC still
  suppresses category colors, uses neutral edges/outlined headings and full
  subtitle opacity, and preserves the theme selection hue.

These are solid-color compositing checks, not a screen-reader speech assessment,
monitor calibration, or a guarantee for arbitrary third-party themes. Decorative
category stripes and intentionally hidden idle remove icons are not claimed as
3:1 interactive indicators. Deprecated GTK rendering APIs are used only in tests.

### Verification and desktop evidence

- Full suite: **996 passed**; normal sidebar: **8 passed**; actual-HC sidebar:
  **8 passed**. Package/test/preview syntax and `git diff --check` passed.
- Logs: `/tmp/oll-colors-{full,sidebar,hc}.log`.
- Isolated preview window 2947867068: synthetic rule activation populated the
  correct reader; native Tab/Tab/Space checked its typed checkbox; F8 verified
  temporary persisted inclusion and invoked its real remove-button signal,
  confirming rule removal, statute preservation and all four updated counts.
  This is keyboard plus signal-driven acceptance, not a physical mouse click.
- F10 restored the clean saved set; F9 added 105 wrapping stress items; F5
  scrolled to the rule. F6/F7 asserted row identity, selection, checkmarks, scroll
  adjustment and Research Set metadata preservation across appearance changes.
  Light/dark screenshots showed readable wrapping and aligned action columns.
- Actual-HC window 2947867070: light/dark screenshots showed neutral outlined
  headings and legible selected rule/controls; activation and appearance
  assertions passed with `get_high_contrast()` true.
- Final window 2947867074: confirmed the Statutes subheading is absent and the
  heading now matches the other compact bands. F11 applied synthetic selected
  states to every category for light/dark screenshot comparison, without changing
  the real selection model. Final checkbox boundary styling was included.
- Preview logs: `/tmp/oll-colors-preview-{acceptance,hc,final}.log`.
  Screenshots were observed, not exported. Synthetic previews were closed normally;
  production Open Law Lens PID 23967 and real data/settings were not targeted.

The preview now also supports F5 (rule activation), F8 (assert checked rule then
remove), and F11 (cycle artificial CSS states). F11 is a visual fixture, not an
assertion that the application supports multiple selected rows. Actual hover,
focus and backdrop cascade behavior is covered by the automated state matrix;
physical pointer and screen-reader speech acceptance remain unverified.

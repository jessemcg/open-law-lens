# Reader masthead validation

## Scope

Source moved to the upper-left balanced column; title remains centered 13 pt
semibold, metadata 10.5 pt, source 9.5 pt, title/subtitle gap 3 logical pixels.
Padding, background, divider, reader text, icons and action callbacks are unchanged.
The right balanced column contains a separately right-aligned action row: grouping
the action row itself would leave its buttons inset when the source is wider.

External-web labels retain full GTK label/accessibility text and a tooltip while
using end ellipsizing and a 24-character natural-width cap. Ordinary provider
names are unellipsized. Header replacement clears source text, tooltip, truncation
settings and visibility before assigning the new title/metadata.

## Checks performed

- Disposable tracked-file project copy, with explicit temporary configuration,
  cache, library and prior-brief database paths; unrelated untracked files excluded.
- `uv run --no-sync python -m unittest discover -s tests`: **1,076 tests passed**.
  Extended header tests cover external-to-ordinary tooltip/truncation reset,
  clearing on navigation, all ordinary provider modes, and preserved citation data.
- `uv run --no-sync python -m py_compile open_law_lens/*.py` and compilation of
  the affected test/preview: passed. `git diff --check`: passed.
- `uv run --no-sync python tests/preview_reader_masthead.py --auto`: **117 native
  layouts per appearance**, repeated for light, dark, native high contrast
  (`ADW_DEBUG_HIGH_CONTRAST=1`), and 150% masthead font sizes
  (`OLL_PREVIEW_LARGE=1`). Dark uses `OLL_PREVIEW_DARK=1`.
- Matrix: requested widths 420/580/880, zero/one/three actions, every provider,
  a long external hostname, long case names, statute/rule subtitles, saved answer,
  prior brief, title-only, and unbroken long identifiers. Assertions check center
  within one pixel, disjoint columns, far-right actions, unellipsized ordinary
  names, complete title/metadata layout widths, and tooltip reset on navigation.
- Short case header at 880 pixels: **58 logical pixels** versus **75** after
  reparenting source back to the third line with a 2-pixel gap and the *new* fonts.
  This is a controlled layout comparison, not a rerun of the original 73-pixel
  pre-change font baseline. Enlarged-font equivalent: 78 versus 102 pixels.
- Native desktop screenshot/accessibility inspection of the separately identified
  `com.mcglaw.OpenLawLens.MastheadPreview` window confirmed source placement and
  full ordinary name, centered identity, and far-right controls. A combined
  dark/high-contrast/enlarged preview was also inspected. Preview processes stopped.

## Limits and reproduction

The preview reparents the actual production masthead out of a temporary production
window; synthetic action visibility is set directly, without invoking actions.
Discovery hooks are disabled and socket network access is blocked. It never opens
private documents, runs models, or saves production configuration. Without
`--auto`, it leaves a short Google Scholar example visible for manual inspection.

GTK/compositor minimum sizing can exceed the requested narrow width: the initial
420-pixel request was allocated 479 pixels on this desktop, and at enlarged font
sizes some 420-pixel requests needed up to 489 pixels. Assertions use actual bounds;
this is not a claim that every enlarged provider fits a hard 420-pixel constraint.
Full ordinary names, equal side columns and enlarged text impose a minimum width.
Long identifiers wrap without ellipsizing and may make a narrow header very tall.
The existing fixed masthead colors and action styling remain unchanged even in
dark/high-contrast mode; this patch does not redesign their appearance.

No storage migrations, network behavior, settings, CLI, launcher or XREMAP changes.
Production runtime files and pre-existing unrelated untracked files were untouched.
Restart Open Law Lens to load the new widgets and styling.

# Unified Settings alignment — 2026-10-19

Pi inheritance follow-up (2026-10-21): see [validation](pi-inheritance-validation.md)
for missing preferences, model-only effort inheritance and current isolated native
Settings acceptance. Older notes below describe their original validation scope.

Publication: the user subsequently authorized a separate local commit of these changes. No push or maintained-app restart is included; the native-input limitation below remains unresolved. The no-commit statements describe the validation run.

General/Display/Highlights/Agent Model retain the existing single boxed expandable home, one outer scroller and inline compact controls. No retired prompt editor, workflow picker or nested model category was restored. The CourtListener token remains masked.

Save stays open with local feedback and accepts the literal baseline after confirmed persistence. A saved configuration whose main-view refresh fails is reported honestly as saved-but-not-refreshed. Dirty Close offers **Keep Editing / Discard Unsaved Changes**. The session-only fact-pattern action is explicitly labelled immediate and is outside the rollbackable draft. Accepted closure alone clears parent ownership; dirty Settings vetoes main-window teardown before session cleanup. Existing model/default/effort and asynchronous catalog behavior remain intact.

## Agent Model boxed-row follow-up — 2026-10-19

Presentation-only: the existing non-selectable model ListBox now has `boxed-list`.
Both ComboRows, labels, factories, signals and save/catalog logic are unchanged;
there is no new group, scroller, theme color or global CSS override.

Fresh tracked-source-only checkout and paired helper-selected Python 3.13 environment:
`/tmp/oll-boxed-WAY7Ug/{source,env}`. HOME/XDG/Pi/configuration/catalogs were synthetic.
No private state was copied, read or rewritten; no model/network request was needed.

- Focused model/settings/session unittest discovery: **11 passed**, fatal GTK criticals enabled.
  Real widgets assert the shared ListBox parent, `selection_mode=NONE`, `boxed-list`,
  row order and exactly two children; existing structure tests remain unchanged.
- Full unittest suite: **1,207 run, 1,205 passed, 2 skipped**, no failures.
- Actual Settings `--auto`: **passed**, including loading/failure saves, unavailable
  selection retention, effort clamping/defaults, Save staying open, synthetic
  Save/reopen and dirty-close discard. Updated the old preview's immediate-close
  expectation to explicitly discard its dirty draft under the existing contract.
- Compilation, tested-source byte identity and `git diff --check`: **passed**.
- Native GNOME synthetic Settings observed at the compositor's 469px tiling width:
  the selectors have the lighter native card background, rounded corners and
  separator, without the anomalous dark rectangle.
- Final **X11/Xvfb** actual-widget matrix: **15 renders passed** with fatal GTK
  criticals enabled. Light/dark, 900×760 / 520×620 / 469×620, normal/20px text;
  plus held-loading, unavailable-model and refresh-failure views. Readable native
  cards and separator, no horizontal scrolling; disabled rows retain native dimming.
  Enlarged narrow views scroll vertically to show both selectors. The preview
  disables animations, retains its paintable and measures decoration extents for
  exact content dimensions. Earlier Broadway captures had stale frames and were
  rejected; only the final X11 captures are evidence here.

[Light](settings-previews/agent-model-boxed-light.png) ·
[Dark](settings-previews/agent-model-boxed-dark.png) ·
[All 15 views](settings-previews/agent-model-boxed-matrix.png)

**Native input limitation:** exact-window coordinate click on Model and targeted
Tab produced no observable dropdown/focus change despite reported dispatch.
Pointer/keyboard selection of either dropdown, interactive refresh and interactive
Save/reopen are therefore **not accepted**; the latter behavior was verified only
programmatically. No blind replay or maintained-app restart was performed. The
owned preview and render server exited. Logs remain in `/tmp/oll-boxed-WAY7Ug`;
final full-size renders are in `/tmp/oll-settings-preview-rq2g36zn`.
The initial full run's cache-default test failure came from the test runner's
cache override; removing that override inside the disposable checkout yielded the
clean full rerun above. No launcher, mapping, dependency, Pi-runtime, other-repo,
other-computer, commit or push changes.

## Historical alignment validation

Disposable tracked-source copy and Python environment selected through explicit paired UvEnvironments overrides, synthetic HOME/XDG/Pi state and fabricated configuration/catalog/persistence. No actual case materials, CourtListener credential, network/model request, indexing or maintained settings were used.

- Full unittest suite: **1,207 passed**.
- Actual GTK settings/session subset: **3 passed**, with `G_DEBUG=fatal-criticals`.
- Existing categories and password row; actual save path, repeated Save, failed write without baseline acceptance, saved-but-refresh-failed feedback, immediate-action exception, dirty Keep/Discard, ownership and parent-close veto. Existing model behavior is also exercised by the full suite.
- GTK/Broadway home previews at 900×720, 520×620 and 469×620, light/dark and enlarged font. Native rows remain in the single outer scroller with no minimum-size growth.

[Light](settings-previews/settings-home-520-light.png) · [Dark](settings-previews/settings-home-520-dark.png) · [469px](settings-previews/settings-home-469-dark.png) · [Enlarged font](settings-previews/settings-home-large-469-dark.png)

The real GNOME desktop was locked during final observation. Broadway rendering and programmatic GTK signals are not native Wayland keyboard/pointer acceptance; unlocked native traversal and focus delivery remain to check. Synthetic sources/environment/logs remain under `/tmp/gtk-rollout-20261019/OpenLawLens` (`final-full-result.log`, `final-focused.log`); the parent contains bounded preview and foreground test runners. Preliminary background-shell Ctrl-C installer timeouts disappeared in the foreground full-suite rerun. No commit, push, maintained-app restart, launcher change, private-file migration or other-computer action was performed.

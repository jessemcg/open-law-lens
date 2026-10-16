# General source-location settings — 2026-10-16

Local Home-only follow-up to the app-owned workflow/Settings work. No dependencies,
lockfiles, launchers, external repositories, private configuration or real source
archives were changed. Prior uncommitted work was preserved. No paid model calls,
production indexing, migration, cleanup, commit or deployment was performed.

## User-visible behavior

Settings retains **one shared boxed list**, now with four independently expanding
rows: General, Display, Highlights and Agent Models. General contains:

1. CourtListener API Token (masked).
2. Concordance File (existing behavior).
3. **Prior Briefs Folder**: editable path, native folder picker and reset. The row
   displays the default path when no override is saved. Choose/reset edits are
   pending until header **Save**; closing discards them. A new nondefault choice
   must be an existing, readable absolute directory (`~` is expanded). Unchanged
   saved paths do not prevent saving unrelated preferences when temporarily offline.
4. **Case Question Fact Pattern**: existing ODT/PDF choose/reset controls moved
   out of the former separate Case Question category. The explanatory subtitle
   explicitly says it applies immediately to this window only and is not saved.
   Reset still uses Current Case SOCF; closing without Save retains that session
   override. The displayed path is read-only; choose/reset are the actual controls.

Folder Save/reset messages direct the user to **Update Prior Brief Library**.
Save does not scan the archive or move/copy/delete source documents. Existing
query-time indexing for Search Briefs and Prior Briefs is unchanged.

## Shared resolution and archive identity

`prior_briefs_folder` is an active string in AppConfig; empty means default.
Loading it is read-only, nonscalar/non-string JSON falls back to default, and
explicit saves continue to retain all retired prompt compatibility data.

`prior_briefs_dir()` resolves environment directory override → saved folder →
existing project default, expanding/canonicalizing paths. GUI initialization,
Settings reload, CLI operations and preparation of new agent snapshots all use
this resolver. A nonempty directory environment override is also explained in
Settings. `OPEN_LAW_LENS_PRIOR_BRIEFS_DB` remains an explicit index override,
including immutable workspace snapshots; overrides intentionally take priority
rather than being overwritten by preferences.

Normal nondefault archives receive independent app-managed indexes named
`library/prior_briefs-<SHA256-of-canonical-source-root>.sqlite3`. Their new brief IDs
are also root-scoped, so identical relative filenames in different folders cannot
resolve to each other's documents after a switch. The default archive retains
`library/prior_briefs.sqlite3` and its legacy IDs. Existing row IDs are preserved
when re-extracting a row. No old index is moved, purged or rewritten to represent
a different preference; switching back reuses it. If a formerly environment-only
custom archive used the legacy implicit DB, that DB is retained, and the newly
selected root-specific index is populated by a normal explicit/query-time update.
An explicit DB override continues to select the exact requested database.

On folder change, Settings reload swaps the active library and invalidates
phrase-search generations/results. Workers retain a single library reference
through sync/search/backup/list, and completion callbacks for an old archive
cannot publish update status for a new one. Existing active agent sessions remain
bound to their original copied database and workspace-only source-root override;
changing preferences does not rescope their follow-ups or rewrite saved answers.

A missing/unreadable source directory now fails before index writes, including
for the default directory: sync never silently creates a replacement empty source
folder. Recursive scanning raises on directory-access errors rather than treating
an incomplete traversal as document deletion. Source checks/scanning precede the
index update transaction. Existing per-file extraction-error handling remains.

## Acceptance

Validation reused tracked-source-only `/tmp/oll-workflows-kmn52lq6/source` and its
machine-local `/tmp/oll-workflows-kmn52lq6/env`, through absolute
`UvEnvironments/project-env --project ... --environment ... run OpenLawLens ...`.
Settings/cache/DB/archive/XDG paths were temporary; CourtListener token was unset.
No ignored production files or environments were copied.

- **1,132 unittest tests PASS**, 16.164 seconds on the final run.
- Configuration: absent/invalid/new path round trips, read-only load, active
  preferences and inactive retired JSON preservation.
- Backend: default DB/ID compatibility; two folders with identical filenames have
  independent contents/indexes/IDs; returning to a folder reuses its index; source
  originals unchanged; environment and explicit DB overrides; CLI update/DB path;
  existing snapshot contents remain pinned after another folder is selected.
- Safety: missing/custom/default directories, unreadability and recursive scan
  failure preserve index contents and do not create source folders.
- GUI behavior: reload swaps libraries, stale phrase-search results are invalidated,
  mid-worker changes cannot mix libraries, old update callbacks cannot report for
  the newly selected folder.
- Actual SettingsWindow `--auto`: exactly four sibling category rows in one boxed
  list; both source controls inside General; native GTK focus traversal; invalid
  folder rejection, folder selection/cancellation/reset, save/error/reload,
  unsaved-close discard, saved reset to default, session-only fact override,
  unavailable models/refresh failure/profile retention and close guards PASS.
- Native render matrix: collapsed and expanded 900×760 light, expanded 900×760
  dark, enlarged-text 620×760 dark, and bottom-of-models view PASS, with explicit
  allocation assertions and no horizontal scrolling. Final images were visually
  reviewed. General's path controls and immediate-vs-saved descriptions fit;
  narrow single-line paths scroll/truncate within their entries as normal.
- Linux Computer Use observed the synthetic native window and used the synthetic
  controls' native AT-SPI Expand action; readback showed four expanded categories.
  No physical keyboard or operating-system chooser selection is claimed. Chooser
  finish/dismissal paths are exercised with synthetic Gio files/errors.
- **128 Python files compiled** in disposable source; `git diff --check` PASS.
  GTK Vulkan resize warnings were nonfatal; no application traceback in acceptance.

Logs: `/tmp/oll-general-paths-dqgddob4` (`tests-delivery.log`, `auto-delivery.log`,
`matrix-delivery.log`). Final renders: `/tmp/oll-settings-preview-38v4ns42`.
Synthetic manual/automated preview processes were stopped/exited. Existing user
application sessions and real documents were not controlled or closed. The real
`config.json` private SHA-256 matched before/after, without exposing its contents.

Restart the app to load the new controls. No dependency synchronization or private
settings migration is needed; the chosen folder takes effect only when the user
saves through Settings. No existing index needs rebuilding unless a different
source folder is actually chosen or the user requests a normal update.

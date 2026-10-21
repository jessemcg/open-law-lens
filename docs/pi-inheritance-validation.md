# Pi preference inheritance — 2026-10-21

## Policy

No personal `.pi/settings.json` is distributed. The existing local file is retained
byte-for-byte and precisely ignored; only its Git index entry is removed. Missing
checkout and standalone preferences both mean no app override, not a missing-resource
failure or seed request. Before updating older Git checkouts, preserve personal
selections externally: removal of a tracked file can delete an unmodified downstream
copy. Existing standalone XDG preferences are unaffected; paths are not migrated.

Existing RPC effective-state discovery remains read-only. Missing preferences stage
an empty object; malformed, unreadable, symlinked or otherwise unsafe preferences
fail through guarded readers. New model-only shared selections store provider/model
without `thinking`; reasoning remains inherited until deliberately chosen. Saved
explicit efforts remain authoritative. Capability/display fallback alone must not
change a saved profile on unrelated Save. Existing legacy-presence precedence and
opaque unrelated/retired values remain intact; no retired workflow overrides revive.

The wrapper accepts a complete provider/model pair with optional effort and still
rejects partial identities/invalid efforts. No maintained desktop/XREMAP caller sets
this internal pair; command names, external paths and CLI entrypoints are unchanged.
All five workflows retain their fixed preloaded instructions, exact
`read,bash,grep,find,ls` allowlist, no discovery tools/extensions and follow-up/session
semantics. No global/general Pi preferences, compaction or retry defaults are seeded.
The model-store revision/lock/Apply/Recovery contracts remain, and model-only Apply
does not materialize inherited reasoning.

## Validation

Home only, RTX 3090. Tracked/new-source-only disposable copies, paired UvEnvironments
`/tmp` source/environment overrides and temporary HOME/XDG/Pi/cache/state/runtime
were used. No real credentials/documents/research/private preference files were used
for write-producing tests; no paid inference or other-computer access occurred.

- Full unittest suite: **1,238 tests, OK, 6 skipped**, including runtime/model-settings/UI, standalone discovery,
  wrapper, all five workflow instructions, installation/resume/repair and receipts.
- Missing checkout settings, malformed/symlink rejection, explicit model-only saves,
  reasoning inheritance, effective effort display and deliberate capability clamping.
- Actual native GTK `tests/acceptance_pi_inheritance.py`: Computer Use inspected
  inherited state, unrelated font Save, deliberate model choice, refresh failure,
  Save/reopen. Synthetic unknown keys and the model-only profile survived; no Pi
  preferences file was created by unrelated Save. `--auto` repeats these assertions.
- Actual Pi offline RPC with synthetic settings/key: changed global model/effort
  took effect on the next session without copied app defaults; no prompt/API call.
- All five wrapper workflow tests now include global `enableSkillCommands: false`:
  mandatory instructions are still preloaded verbatim and global bytes stay intact.
- Shell/resource/whitespace checks, scoped Git review, private-file byte/stat
  preservation and unchanged bootstrap/installer publication contract. The new
  internal guarded staging helper is part of resource readiness validation.

Evidence is machine-local at `/tmp/pi-defaults-start`. Initial PTY Ctrl+C failures
were inherited ignored SIGINT from background test jobs; normal-signal reruns pass
without installer changes. No clean-distro or paid-model quality certification is
claimed. README files and their one-line commands are unchanged by user request.
Rollback is a source revert, not restoration/reset of private settings or research.

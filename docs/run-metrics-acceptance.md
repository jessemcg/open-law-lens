# Open Law Lens run-metrics acceptance

2026-09-22, home desktop. Installed Pi 0.87.1 / Node 22.23.1.

## Shipped scope

- Every Pi-backed workflow explicitly loads sibling `PiRunMetrics/run-collector.ts` alongside the preexisting web-access extension where applicable. Discovery remains disabled and the exact tool restrictions, system/skill preload, and model selection are unchanged.
- `profile_key` travels through launch metadata. Tags distinguish `law`, `research_cache`, `prior_briefs`, `assess_argument`, and `subsequent_treatment` even though Subsequent Treatment uses general mode. Local Search Briefs bypasses Pi launch.
- Default archive: `OpenLawLens/.run-metrics/runs/YYYY-MM-DD/<uuid>.jsonl`, with `/.run-metrics/` Git-ignored. Absolute `PI_RUN_METRICS_ROOT` overrides it. Private permissions are retained; Dropbox may sync the project directory. No migration/deletion of old records or traces.
- Copy Trace controls, availability updates, callback, export-only helpers/imports/tests are removed. Workspace session JSONL discovery/persistence, answer parsing, generation guards, background rendering, Answer/Session/Save, and ordinary cleanup remain. No telemetry content goes into prompts or tools.

## Automated acceptance

A disposable tracked-source copy at `/tmp/oll-metrics-acceptance-ko5g4n3b` excluded private config/data and unrelated untracked/conflict files. The existing uv environment was selected with `UV_PROJECT_ENVIRONMENT` and `--no-sync`; all cache/library/prior-brief overrides pointed into the temporary copy.

- `uv run --no-sync python -m unittest discover -s tests`: **1069 tests pass**, including existing answer-completion/generation/session and local-search coverage.
- Python compilation, wrapper `bash -n`, and `git diff --check` pass.
- Git ignore checked directly and through a disposable test repository.
- Wrapper tests verify all workflow tags, project-local root, root override with spaces, missing/relative collector paths, disabled collection, unchanged tool allowlists, research-only web loading, and retained `pi-sessions` transport (no `--no-session`).
- `tests/test_run_metrics_sdk.py` invokes the **production wrapper** with `tests/metrics_sdk_fixture.mjs` standing in for the Pi executable. It uses the installed real SDK and shared observer, disposable auth/settings/session files, a scripted provider and synthetic web-access stand-in; fetch is prohibited. It does not call a real model or the production web package.
- Across all five workflows, enabled/disabled/missing-collector/unwritable-root variants yield identical provider contexts, actual available tools, and final answer text. Persisted SDK JSONL is read back through the production final-answer parser.
- One scripted retry yields one metrics run with two low-level cycles; a later settled question yields another run. Exact first-run totals: three finalized assistant responses, 33 input tokens, one `read`, and exact UTF-8 text-result bytes. Two files remain despite disabled/missing/unwritable variants. Files/directories are `0600`/`0700`; canary prompt/answer/tool/error content and source filename are absent from records.

Run SDK acceptance on an isolated copy with an absolute `PI_METRICS_TEST_COLLECTOR` if the sibling project is not beside that copy. `PI_METRICS_TEST_SDK` can identify the installed SDK package when it is not adjacent to Node. These are test-only controls.

## Disposable desktop acceptance

`tests/preview_run_metrics.py` creates temporary HOME/config/cache/state/library and a separately identified application/window; current-case discovery and network/model work are blocked. Production asynchronous session reading and answer rendering display two synthetic answer revisions.

Linux Computer Use observed PID 26056, titled **Open Law Lens — Synthetic Metrics Acceptance**:
- Copy Trace absent; Answer, Session, Save, and Hide retained.
- Latest synthetic answer (revision 2) visibly rendered with Markdown emphasis.
- Click Session: terminal visible. Click Answer: latest answer visibly restored.
- Click Save: synthetic answer appears under Saved Answers in the temporary Research Cache and in the reader. No real research data/settings are touched.

The preview process was closed afterward. `--auto` repeats its internal rendering/control assertions and exits. This desktop check used synthetic JSONL, not a live provider inside VTE; the real SDK/wrapper accounting is separately tested above.

## Activation, analysis, rollback

Restart Open Law Lens to remove the old button. New embedded sessions load the observer. From the project directory:

```sh
python3 ../PiRunMetrics/analyze_runs.py --root "$PWD/.run-metrics/runs" --app open-law-lens --days 14
```

Reports stay in private XDG state. Use `PI_RUN_METRICS_ENABLED=0` to disable collection or remove the observer load; do not delete archives. Missing instrumentation cannot claim complete capture. Hard kills may leave unfinished records. No exact retry count, external billing coverage, or substantive-answer assessment is claimed.

The shared pilot's remaining lifecycle/schema acceptance matrix and Prose/EmailAgent Copy Trace removal remain separate pending work. No changes to those apps, models, private settings, PiPlanner, retired Run Review, Desktop_Files, or XREMAP were made here.

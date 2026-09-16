# Responsive final-answer completion

## Implementation

Previously, the GTK polling callback read the session JSONL and synchronously
rendered markdown, quote/source navigation, citation links, and text tags. An
agent could already have exited while that work still blocked the desktop.

The normal polling path now uses one background worker per session generation
for discovery, log reading, markdown preparation, and source/link matching.
`answer_rendering.py` produces a widget-free text/style plan. GTK consumes the
plan in approximately 6 ms idle batches, with text insertions capped at 8,192
characters. Individual GTK operations are not preemptible, so this is a
scheduling target, not a strict upper bound on every operation. Large answers
avoid an immediate full offscreen height measurement.

The finishing spinner remains active through preparation and rendering. A
low-priority idle completes the transition after normal GTK layout/paint work
has had an opportunity to run. Session output remains accessible while work is
pending; saving is disabled until finalization. Errors expose Session output
and release finishing state. Generation and render IDs reject obsolete work
following cancellation, replacement, or window close. An agent exit during an
in-flight read causes one final follow-up read.

No model, reasoning settings, prompts, archive schema, private configuration,
launcher, or XREMAP changes are required. Existing synchronous rendering is
retained for compatibility and parity checks; the live completion path uses
the prepared, batched renderer.

## Validation

`tests/test_answer_rendering.py` covers worker/main-loop separation, finishing
state and spinner lifecycle, the exit/read race, stale cancellation, read and
render failures, Unicode/source offsets, and text/link parity with the existing
GTK formatter in all four agent modes. The existing polling test is adapted to
the worker and idle handoff.

`tests/preview_answer_completion.py` runs a disposable GTK application with a
temporary synthetic archive/configuration and blocked networking. It injects a
delayed log read and a 300-paragraph answer containing 300 links, asserts that
the spinner stays active while finishing, measures a 10 ms GTK heartbeat, and
automatically closes. Run it only with isolated config/cache/state directories,
not against the real archive. `OLL_COMPLETION_PREVIEW_DELAY` changes the injected
delay; the default is 8 seconds.

The complete isolated suite passed **1,015 tests**; package syntax and Git
whitespace checks also passed. A local synthetic run recorded a maximum
heartbeat gap of **0.063 seconds**, 765 heartbeat ticks, and two reads (including
the exit recheck). A second run with a 20-second injected delay also passed,
with a **0.063-second** maximum gap and 1,916 heartbeat ticks. Native desktop
inspection and interaction were also performed on a delayed synthetic preview.
These are bounded synthetic responsiveness checks, not proof of an absolute
latency bound for arbitrarily large logs, pathological regex inputs, or all
compositor/GPU conditions. No production session or private archive was used,
and no model calls were made.

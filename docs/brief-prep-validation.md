# Brief Prep cutover

Open Law Lens owns all three workflows. Current Case TUI sends a selected folder
through `project-env run OpenLawLens open-law-lens app --brief-prep KIND
--case-dir ABSOLUTE`. Lens acknowledges cold and warm requests without echoing a
case identifier. The acknowledgement means the request reached Lens, not that
preparation or research finished. Busy requests are rejected, not replayed.
The TUI registry and its matching release binary must be deployed together.

## Local validation (synthetic only)

- Nested PDFs exercised all variants, draft/duplicate ranking, wrong-case and
  wrong-party rejection, ambiguity, opposition without an opening brief, local
  OCR failure, unchanged source files, and restricted schema-v2 record staging.
- The native private-bus preview used GTK, the production wrapper, a fake Pi
  session and Unix follow-up transport. It verified cold, warm and busy requests,
  a case path with an apostrophe, menu access without an SOCF, selection changes
  during preparation, Answer, an interrupted turn's Save guard, linked reader
  rendering, and a checked Brief Prep report surviving a Research Set round-trip.
- The real GTK sidebar tests cover light, dark and high contrast. The installed
  Pi SDK fixture exercised all eight workflows with metrics enabled, disabled,
  missing or unwritable, without using a model provider or tagging case identity.
- The Current Case release was tested with synthetic case roots in a PTY: Enter
  and double-click, exact Lens arguments, an interactive dashboard while waiting,
  missing runtime, and no Pi fallback. The seven Worker workflows and inactive
  Analysis inventory were checked separately.
- LightOnOCR's optional `--page-breaks` CLI was checked with a mocked pipeline.
  No live GPU OCR or paid case analysis was performed; these checks do not
  establish extraction accuracy on a particular scan or legal quality.

Reopen the two applications after finishing any in-progress work. Rollback uses
the matching versions of Lens, the TUI registry/resources and TUI release binary.
It does not roll back user research, case files, or saved model preferences.

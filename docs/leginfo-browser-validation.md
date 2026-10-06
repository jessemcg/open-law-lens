# LegInfo default-browser recovery (2026-10-06, Home)

## Cause and contract

The direct section request returned HTTP 403 with `Server: cloudflare`,
`Cf-Mitigated: challenge` and a `Just a moment...` HTML title. The identical
section URL displayed substantive legislation in a real browser.

`fetch_leginfo_statute` retains direct HTTP first. Only HTTP 403 or a returned
browser-verification title triggers one `leginfo_browser.recover_leginfo_text`
attempt. Other HTTP errors (including 404/429), network failures, and invalid
ordinary bodies do not start the browser or initiate retries.

The browser path:

- Resolves the current default HTTPS handler at each launch through the same
  bounded, detached Gio launcher used by Scholar. `launch_scholar_url` retains
  its own Scholar-only destination validation; the shared launcher is beneath
  that validation. The statute caller builds only the official current-section
  URL. No configured default/browser profile is changed.
- Uses the existing first-party Computer Use MCP client and cross-process
  `RecoveryLock`. No model, search, alternative source, cookie extraction,
  screenshots, coordinates, typing, or challenge interaction is added.
- Holds the nonblocking lock through clipboard read and text validation, shared
  with Scholar recovery. Browser operations use a 60-second job budget; launch,
  individual MCP requests, and clipboard reads also have their existing bounds.
- Requires exact compositor frame, browser address-bar endpoint/query, selected
  document title and numeric window ID. Handles browser scheme elision and the
  official section's optional terminal dot without accepting historical pages,
  added/duplicated query keys, foreign hosts, or a body hyperlink as the address.
- Activates only the verified numeric browser window before copying. This is
  necessary when Gio opens the new tab without granting foreground focus.
  Rejects focused editable document controls, rechecks the URL/document around
  copy, and requires successful key-tool results for Ctrl+A and Ctrl+C.
- Reads the regular clipboard with the existing bounded reader (4 MiB cap).
  Requires matching code header, exact section heading, substantive prose and
  the complete enactment end-note line. Multiple section bodies reject. The
  common LegInfo extractor still validates the resulting body. Unsupported
  layouts fail closed rather than accepting a navigation page or a snippet.
- Returns `retrieval_mode: browser_clipboard` with the official source URL and
  empty `source_html`; it never stores reconstructed markup as original HTML.
  Direct results report `retrieval_mode: direct_http`.
- Leaves human-verification controls untouched. An automatic `Just a moment`
  interstitial can settle within the budget; an unresolved check gives retry
  instructions. Focus restoration is best-effort, never overriding a later
  deliberate user switch or hiding a detected challenge.

The existing caller performs Research Cache insertion only after successful
retrieval. GUI workers retain their reader/cache-generation guards. There are
no durable case imports, configuration changes, cache migrations, dependencies,
launcher/CLI contract changes, or agent prompt/model changes.

## Validation

- 25 new network-free tests: exact URL and frame scoping; hidden document
  exclusion; conflicting/absent code and section; incomplete/nonsubstantive
  copies; busy lock; timeouts; desktop failure; human challenge; editable focus;
  tab changes during selection/copy; failed keys; focus restoration; recovery
  failure without cache insertion; direct success; HTTP 403/200 challenge
  triggers; unrelated HTTP/network errors; truthful provenance.
- Initial full suite: **1,115 tests passed** (existing GTK deprecation warnings).
  After the cold-completion follow-up below: **1,122 tests passed**.
- Actual Home default-handler browser recovery returned:
  - Government Code § 815.6: 401 characters.
  - WIC § 300: 9,654 characters, including its final amendment note.
  - WIC § 224.2: 10,536 characters, including its final amendment note.
- `tests/preview_leginfo_browser.py` exercised the real GUI lookup worker,
  default-browser fallback, reader rendering, and temporary Research Cache for
  GOV § 815.6. Its assertions passed with an empty durable case library; native
  AT-SPI and screenshot confirmed the reader and one statute sidebar entry.
  Initial GUI acceptance exposed background-browser focus; exact-ID activation
  fixed that failure and the second isolated run passed.
- The live checks also exposed Firefox address-bar HTTPS scheme elision, now
  covered by a regression assertion. No hardcoded Firefox launch was added.

Run from the checkout using the absolute project-env helper:

```sh
P=/home/jesse/Dropbox/MCGLAW/config_files/scripts/PROJECTS/UvEnvironments/project-env
"$P" run OpenLawLens python -m unittest discover -s tests
"$P" run OpenLawLens python tests/preview_leginfo_browser.py
```

## Cold autocomplete/Enter follow-up

The running production app could display `WIC 300` completions after warm-up,
so this was not a universal loss of statute parsing. The cold path nevertheless
had two reproducible defects: `_lookup_text_from_entry` synchronously refreshed
all suggestions on GTK if the initial index had not completed, and the completion
publisher checked focus on the GtkEntry wrapper rather than its focused GtkText
child. A read-only SQLite backup of the current library into temporary state
measured **5.007 seconds** for its saved-case suggestion scan. The original
single-stage index withheld all concordance suggestions until that scan finished.

The fix publishes concordance suggestions early via GTK idle while the library
scan continues in its worker. Pending edits use the current partial index.
Publication recognizes descendant entry focus. Fully qualified statutes/rules
are dispatched directly; other entry resolution uses only the in-memory snapshot
and requests an asynchronous refresh, never library I/O from Enter.

Seven new regression tests cover these cold paths and exact enactment identity.
`tests/preview_leginfo_browser.py --cold` uses a synthetic concordance and an
intentionally four-second library worker, checks that suggestions are visible
with the real inner-widget focus before the library finishes, submits `WIC 300`
through the production entry handler, and retrieves/renders it via the real
browser fallback into temporary state. Live results: **Enter returned in 0.001
seconds**, maximum **50-ms heartbeat gap 0.059 seconds**, complete reader and
Research Cache, empty durable library. An earlier isolated WIC300 GUI probe also
succeeded. The user's exact failing input was not supplied; other input-specific
failures or longer freezes are not thereby ruled out. Production entry was
briefly populated with `WIC 300` to observe suggestions, then restored to empty;
no production lookup was submitted.

The preview creates fresh `/tmp/oll-leginfo-preview-*` configuration/cache/library
state, disables current-case refresh, and makes a real government retrieval. It
uses the browser/regular clipboard and leaves its separate synthetic window for
inspection. Close the preview normally. Production research, settings, and open
application state were not changed or restarted. Save any unsaved Research Set
and restart the production GUI to load the update. Other computers/browser
engines and interactive human challenges were not live-tested; barrier and
failure behavior is covered with synthetic fixtures.

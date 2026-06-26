# Open Law Lens

Open Law Lens is a minimal legal research app focused on looking up published
case citations through the CourtListener API.

## Usage

Set a CourtListener token when available:

```bash
export COURTLISTENER_TOKEN="your-token"
```

You can also save the token from the app menu under Settings. That writes a
local `config.json`, which is ignored by Git.

Launch the app:

```bash
uv run open-law-lens app
```

Look up a citation from the CLI:

```bash
uv run open-law-lens lookup-citation "576 U.S. 644"
```

Print the first matching opinion text:

```bash
uv run open-law-lens lookup-citation "576 U.S. 644" --text
```

Show saved library cases:

```bash
uv run open-law-lens show-library
```

Show Research Cache cases listed in the sidebar:

```bash
uv run open-law-lens show-cache
```

Print the durable library database path:

```bash
uv run open-law-lens library-db
```

Clear Research Cache data without deleting saved library cases:

```bash
uv run open-law-lens clear-cache
```

## Library and Cache

Open Law Lens keeps a durable SQLite case library at
`library/open_law_lens.sqlite3` by default. The library stores raw
CourtListener JSON plus display-ready opinion text. When CourtListener provides
explicit reporter page markers, the app preserves them inline as markers such
as `[*373]` and renders those markers prominently in the reader.

The `cache/` directory remains a disposable JSON API cache. Lookups check the
library first, then the JSON cache, then CourtListener. Cache or API hits are
saved into the library for faster future access.

The app sidebar is the **Research Cache**, not the full library. Clearing the
Research Cache removes those visible sidebar cases while preserving the durable
library so future lookups can still be served without another API call.

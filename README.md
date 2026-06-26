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

Show cached lookups:

```bash
uv run open-law-lens show-cache
```

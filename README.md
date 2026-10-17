# Open Law Lens

<img src="open-law-lens-icon.svg" alt="Open Law Lens icon" width="96" align="right">

A Linux desktop app for reading and researching California legal authority.
Uses [CourtListener](https://www.courtlistener.com/), a project of
[Free Law Project](https://free.law/about/), for case lookup and research,
and the [Pi coding agent](https://pi.dev/) for optional AI questions.

- Look up California cases, statutes, and Rules of Court in a focused reader.
- Keep authorities, highlights, saved answers, and named research sets locally.
- Search your own prior briefs and read linked quotations in context.
- Ask AI research questions, follow up, or assess a question against supplied facts.

## Install

Open Law Lens is intentionally distributed as source rather than a Flatpak or Debian package so that it can be easily modified by a coding agent.
The installer has been tested with Ubuntu and Fedora.

With `curl` installed, run as your normal user—not with sudo:

```bash
curl -fsSL https://raw.githubusercontent.com/jessemcg/open-law-lens/main/scripts/install-bootstrap.sh | bash
```

Installs the latest `main` code into `~/OpenLawLens` and asks before installing
missing dependencies. Settings and research use per-user XDG storage, outside the
editable checkout. Open Law Lens installs fully without Pi or an AI account.

The installer includes standalone Linux Computer Use for automated Google Scholar
recovery. Browser/desktop permission setup is separate. After confirming the app
is installed, setup offers Pi if missing: press Enter to install or type `skip`.
Skipping, canceling, or failing optional Pi setup leaves the application installed.

[Installation options, troubleshooting, and removal](docs/source-install.md)

## Resume or uninstall

### Resume installation

```bash
curl -fsSL https://raw.githubusercontent.com/jessemcg/open-law-lens/main/scripts/install-bootstrap.sh | bash -s -- --resume
```

### Uninstall Open Law Lens

Close the application and embedded sessions, then run:

```bash
"$HOME/.local/bin/open-law-lens-uninstall"
```

This keeps your source checkout, settings, library, research, saved answers,
prior briefs, sessions, and Pi. See [removal options](docs/source-install.md#removal)
for separately confirmed cleanup.

### Uninstall Pi

Run its official installer and choose **Uninstall Pi**:

```bash
curl -fsSL https://pi.dev/install.sh | sh
```

Pi may also serve other apps; removing it disables their Pi features, including
Open Law Lens's AI questions. Pi credentials and saved sessions are retained.

## Get started

Launch **Open Law Lens** from your applications menu or run `open-law-lens app`.

Get a [CourtListener API token](https://www.courtlistener.com/profile/api-token/)
and save it in the app menu under **Settings**. Enter a case citation such as
`11 Cal.5th 614`, a qualified statute such as `Welf. & Inst. Code, § 300`, or
`Cal. Rules of Court, rule 8.1115` to look up authority.

For optional AI features, open Pi and use `/login` to enter an API key or sign in.
Then choose available models in Open Law Lens **Settings → Agent Models**.
See the [user guide](docs/user-guide.md) for research, prior briefs, and reader tools,
and [setup instructions](docs/source-install.md#standalone-computer-use) for browser
readiness.

AI questions may send selected facts and research to your chosen provider and
may incur charges. Check confidentiality terms before using sensitive material;
verify answers, quotations, and current law against the sources.

## License

See [LICENSE](LICENSE).

#!/usr/bin/env python3
"""Print the simple latest-main installation command.

--expanded shows the reviewed bootstrap; --inline preserves the self-contained
form that can provision a missing downloader. Nothing is downloaded or installed.
"""
import argparse
from pathlib import Path
import shlex


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--expanded", action="store_true")
    mode.add_argument("--inline", action="store_true")
    mode.add_argument("--download-first", action="store_true")
    parser.add_argument("--downloader", choices=("curl", "wget"), default="curl")
    args = parser.parse_args()
    scripts = Path(__file__).resolve().parent
    script = (scripts / "download-bootstrap.sh.in").read_text()
    if args.expanded:
        print(script, end="")
    elif args.inline:
        escaped = script.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
        print("bash -c $'" + escaped + "' --")
    else:
        url = "https://raw.githubusercontent.com/jessemcg/open-law-lens/main/scripts/install-bootstrap.sh"
        if not args.download_first:
            download = f"curl -fsSL {url}" if args.downloader == "curl" else f"wget -qO- {url}"
            print(download + " | bash")
            return
        download = (f'curl -fL --proto =https --tlsv1.2 {url} -o "$f"' if args.downloader == "curl"
                    else f'wget --https-only -O "$f" {url}')
        # Unique mode-600 file, no pipe/process substitution, and no execution on
        # a failed/partial download. Cleanup preserves the download/child status.
        loader = r'f=$(mktemp) || exit; trap "rm -f \"\$f\"" EXIT; ' + download + ' && bash "$f" "$@"'
        print(shlex.join(["bash", "-c", loader, "--"]))


if __name__ == "__main__":
    main()

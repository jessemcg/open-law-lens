#!/bin/sh
# Public bootstrap: install the latest main source.
set -eu
umask 077
export LC_ALL=C
ref='main'
[ "$(id -u)" != 0 ] || { printf '[FAIL] Run as the desktop user.\n'; exit 1; }
[ ! -e /run/ostree-booted ] && [ ! -d /sysroot/ostree ] || { printf '[FAIL] Immutable desktop unsupported.\n'; exit 1; }
. /etc/os-release
family=''
case "${ID:-}:${VARIANT_ID:-}" in bazzite:*|silverblue:*|kinoite:*|fedora:silverblue|fedora:kinoite|fedora:coreos) exit 1 ;; esac
if [ "${ID:-}" = ubuntu ]; then
  case "${VERSION_ID:-}" in 24.04|26.04) ;; *) printf '[FAIL] Unsupported Ubuntu release.\n'; exit 1 ;; esac
fi
case " ${ID:-} ${ID_LIKE:-} " in
  *' ubuntu '*)
    case "${UBUNTU_VERSION_ID:-${VERSION_ID:-}}:${UBUNTU_CODENAME:-}" in
      24.04:*|26.04:*|*:noble|*:resolute) family=apt ;;
      *) printf '[FAIL] Unsupported Ubuntu base.\n'; exit 1 ;;
    esac ;;
  *' fedora '*)
    case "${FEDORA_VERSION_ID:-${VERSION_ID:-}}" in 43|44) family=dnf ;; *) exit 1 ;; esac ;;
  *) printf '[FAIL] Unsupported distro/base.\n'; exit 1 ;;
esac
case "$(uname -m)" in x86_64|aarch64) ;; *) exit 1 ;; esac
temp=$(mktemp -d -t open-law-lens-download.XXXXXXXX) || exit 1
trap 'rm -rf -- "$temp"' EXIT HUP INT TERM
snapshot() {
  if [ "$family" = apt ]; then
    dpkg-query -W '-f=${binary:Package}\t${db:Status-Status}\n' > "$temp/snapshot-raw"
    awk '$2 == "installed" {sub(/:.*/, "", $1);print $1}' "$temp/snapshot-raw" | sort -u
  else
    rpm -qa --qf '%{NAME}\n' > "$temp/snapshot-raw"
    sort -u "$temp/snapshot-raw"
  fi
}
introduced=''
if ! command -v curl >/dev/null 2>&1 && ! command -v wget >/dev/null 2>&1; then
  printf '[ACTION] No downloader. Preview installing curl from official repositories.\n'
  snapshot > "$temp/before"
  if [ "$family" = apt ]; then
    apt-get --simulate install curl > "$temp/preview"
    cat "$temp/preview"
    if grep -q '^Remv ' "$temp/preview"; then printf '[FAIL] Transaction would remove packages.\n'; exit 1; fi
  else
    status=0
    dnf --assumeno install curl > "$temp/preview" 2>&1 || status=$?
    cat "$temp/preview"
    [ "$status" -le 1 ] || exit 1
    if grep -Eq 'Removing|Erasing|No match for argument|Unable to find|Failed to|Error:' "$temp/preview"; then
      printf '[FAIL] Unsafe or unavailable bootstrap transaction.\n'; exit 1
    fi
  fi
  printf '[WAIT] Authorize curl transaction (sudo still asks separately)? Type yes: ' >/dev/tty
  IFS= read -r answer </dev/tty
  [ "$answer" = yes ] || exit 1
  if [ "$family" = apt ]; then sudo apt-get install curl; else sudo dnf install curl; fi
  snapshot > "$temp/after"
  introduced=$(comm -13 "$temp/before" "$temp/after" | tr '\n' ' ')
  printf '[WARN] Bootstrap-introduced packages retained if later download fails: %s\n' "$introduced"
fi
url="https://raw.githubusercontent.com/jessemcg/open-law-lens/$ref/install.sh"
printf '[ACTION] Downloading the Open Law Lens installer...\n'
if command -v curl >/dev/null 2>&1; then
  curl -fL --proto '=https' --tlsv1.2 "$url" -o "$temp/install.sh"
else wget --https-only -O "$temp/install.sh" "$url"; fi
printf '[OK] Download complete. Starting Open Law Lens setup.\n'
printf 'Setup will ask before installing missing dependencies. Pi is optional after Open Law Lens is installed.\n'
OPEN_LAW_LENS_INSTALL_REF="$ref" OPEN_LAW_LENS_BOOTSTRAP_PACKAGES="$introduced" bash "$temp/install.sh" "$@" </dev/tty

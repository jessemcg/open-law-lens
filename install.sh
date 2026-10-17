#!/usr/bin/env bash
# Complete-file bootstrap; never execute a partially downloaded stream.
set -euo pipefail
umask 077
export LC_ALL=C
if (( EUID == 0 )); then printf '[FAIL] Run as the desktop user, not root.\n' >&2; exit 1; fi
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
dry_run=0
for arg in "$@"; do
  [[ "$arg" != --dry-run && "$arg" != --help && "$arg" != -h ]] || dry_run=1
done
# Reject unsupported hosts before even bootstrapping Python/curl.
if [[ -e /run/ostree-booted || -d /sysroot/ostree ]]; then
  printf '[FAIL] Immutable/rpm-ostree systems are not supported.\n' >&2; exit 1
fi
source /etc/os-release
family=''
base=" ${ID:-} ${ID_LIKE:-} "
case "${ID:-}:${VARIANT_ID:-}" in
  bazzite:*|silverblue:*|kinoite:*|fedora:silverblue|fedora:kinoite|fedora:coreos)
    printf '[FAIL] Immutable desktop provisioning is unsupported.\n' >&2; exit 1 ;;
esac
if [[ "$base" == *' ubuntu '* ]]; then
  version="${UBUNTU_VERSION_ID:-${VERSION_ID:-}}"
  if [[ "$version" != 24.04 && "$version" != 26.04 && ( "${ID:-}" == ubuntu || ( "${UBUNTU_CODENAME:-}" != noble && "${UBUNTU_CODENAME:-}" != resolute ) ) ]]; then
    printf '[FAIL] Requires Ubuntu base 24.04 or 26.04.\n' >&2; exit 1
  fi
  family=apt
elif [[ "$base" == *' fedora '* && ( "${FEDORA_VERSION_ID:-${VERSION_ID:-}}" == 43 || "${FEDORA_VERSION_ID:-${VERSION_ID:-}}" == 44 ) ]]; then
  family=dnf
else printf '[FAIL] Unsupported distribution/base.\n' >&2; exit 1
fi
case "$(uname -m)" in x86_64|aarch64) ;; *) printf '[FAIL] Unsupported architecture.\n' >&2; exit 1 ;; esac
bootstrap_before=()
bootstrap_added=()
need=()
command -v python3 >/dev/null || need+=(python3)
if [[ ! -f "$root/scripts/open_law_lens_maintenance.py" ]]; then
  command -v curl >/dev/null || command -v wget >/dev/null || need+=(curl)
fi
if (( ${#need[@]} )); then
  printf '[ACTION] Bootstrap prerequisites missing: %s\n' "${need[*]}"
  if (( dry_run )); then printf '[WARN] Install prerequisites first to continue full dry-run.\n'; exit 1; fi
  if [[ "$family" == apt ]]; then
    snapshot="$(dpkg-query -W '-f=${binary:Package}\t${db:Status-Status}\n')"
    mapfile -t bootstrap_before < <(printf '%s\n' "$snapshot" | awk '$2 == "installed" {sub(/:.*/, "", $1); print $1}')
    preview="$(apt-get --simulate install "${need[@]}")"
    printf '%s\n' "$preview"
    if grep -q '^Remv ' <<<"$preview"; then printf '[FAIL] Bootstrap would remove packages.\n'; exit 1; fi
  else
    snapshot="$(rpm -qa --qf '%{NAME}\n')"
    mapfile -t bootstrap_before <<<"$snapshot"
    status=0
    preview="$(dnf --assumeno install "${need[@]}" 2>&1)" || status=$?
    printf '%s\n' "$preview"
    if (( status > 1 )) || grep -Eq 'Removing|Erasing|No match for argument|Unable to find|Failed to|Error:' <<<"$preview"; then
      printf '[FAIL] Unsafe or unavailable bootstrap transaction.\n'; exit 1
    fi
  fi
  printf '[WAIT] Authorize shown bootstrap transaction? Type yes: ' >/dev/tty
  IFS= read -r answer </dev/tty
  [[ "$answer" == yes ]] || exit 1
  if [[ "$family" == apt ]]; then sudo apt-get install "${need[@]}"; else sudo dnf install "${need[@]}"; fi
  # All transaction additions (including transitives), not just requested names.
  if [[ "$family" == apt ]]; then
    snapshot="$(dpkg-query -W '-f=${binary:Package}\t${db:Status-Status}\n')"
    mapfile -t after < <(printf '%s\n' "$snapshot" | awk '$2 == "installed" {sub(/:.*/, "", $1); print $1}')
  else
    snapshot="$(rpm -qa --qf '%{NAME}\n')"
    mapfile -t after <<<"$snapshot"
  fi
  for name in "${after[@]}"; do
    found=0
    for prior in "${bootstrap_before[@]}"; do [[ "$name" != "$prior" ]] || found=1; done
    (( found )) || bootstrap_added+=("$name")
  done
fi
export OPEN_LAW_LENS_BOOTSTRAP_PACKAGES="${OPEN_LAW_LENS_BOOTSTRAP_PACKAGES:-} ${bootstrap_added[*]}"
if [[ -f "$root/scripts/open_law_lens_maintenance.py" ]]; then
  exec python3 -I "$root/scripts/open_law_lens_maintenance.py" install --payload-root "$root" "$@"
fi
# Fresh installs follow the latest main; explicit commits remain usable for diagnostics.
ref="${OPEN_LAW_LENS_INSTALL_REF:-main}"
if [[ ! "$ref" =~ ^(main|[0-9a-f]{40})$ ]]; then
  printf '[FAIL] Source ref must be main or a full commit.\n' >&2; exit 1
fi
temporary="$(mktemp -d -t open-law-lens-bootstrap.XXXXXXXX)"
trap 'rm -rf -- "$temporary"' EXIT
mkdir -p "$temporary/scripts"
fetch() {
  printf '[ACTION] Download complete file: %s\n' "$1"
  if command -v curl >/dev/null; then curl --fail --location --proto '=https' --tlsv1.2 "$1" --output "$2";
  else wget --https-only --output-document="$2" "$1"; fi
}
fetch "https://raw.githubusercontent.com/jessemcg/open-law-lens/$ref/scripts/open_law_lens_maintenance.py" "$temporary/scripts/open_law_lens_maintenance.py"
export OPEN_LAW_LENS_INSTALL_REF="$ref"
python3 -I "$temporary/scripts/open_law_lens_maintenance.py" install --payload-root "$temporary" "$@"

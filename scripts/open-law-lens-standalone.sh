#!/usr/bin/env bash
# Complete source-install entry point. Provisioning is a separate explicit step.
set -euo pipefail
umask 077
source_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
environment="${OPEN_LAW_LENS_ENVIRONMENT:-${HOME}/.local/share/open-law-lens/environment}"
if [[ "$environment" != /* || ! -x "$environment/bin/python" ]]; then
  printf 'Open Law Lens is not provisioned. See docs/portability.md; launch never installs dependencies.\n' >&2
  exit 1
fi
# Avoid inherited Python/uv identity from a calling application.
unset PYTHONHOME PYTHONPATH VIRTUAL_ENV UV_PROJECT_ENVIRONMENT
export PYTHONDONTWRITEBYTECODE=1
export OPEN_LAW_LENS_STORAGE=standalone
export OPEN_LAW_LENS_CLI_BIN="$environment/bin/open-law-lens"
"$environment/bin/python" "$source_root/scripts/standalone-runtime.py" --check
exec "$OPEN_LAW_LENS_CLI_BIN" "$@"

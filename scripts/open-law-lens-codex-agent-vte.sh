#!/usr/bin/env bash
set -euo pipefail

prompt_file="${OPEN_LAW_LENS_AGENT_PROMPT_FILE:-}"
cache_root="${OPEN_LAW_LENS_CACHE_DIR:-${XDG_CACHE_HOME:-${HOME:-}/.cache}/open-law-lens}"
codex_bin="${CODEX_BIN:-codex}"
codex_profile="${CODEX_PROFILE:-fireworks}"
workspace_parent="${XDG_CACHE_HOME:-${HOME:-}/.cache}/open-law-lens/agent-workspaces"

mkdir -p "$workspace_parent"
workspace="$(mktemp -d "$workspace_parent/workspace.XXXXXX")"

cleanup() {
  rm -rf "$workspace"
}
trap cleanup EXIT

if [[ -z "$prompt_file" || ! -f "$prompt_file" ]]; then
  printf 'Open Law Lens agent prompt file not found: %s\n' "$prompt_file" >&2
  exit 2
fi

if ! command -v "$codex_bin" >/dev/null 2>&1; then
  printf 'Codex executable not found: %s\n' "$codex_bin" >&2
  exit 127
fi

cd "$workspace"
mkdir -p "$workspace/tmp"
export TMPDIR="$workspace/tmp"
export OPEN_LAW_LENS_CACHE_DIR="$cache_root"
prompt="$(cat "$prompt_file")"

"$codex_bin" \
  --profile "$codex_profile" \
  -C "$workspace" \
  --sandbox workspace-write \
  "$prompt"


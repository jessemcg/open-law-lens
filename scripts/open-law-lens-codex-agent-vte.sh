#!/usr/bin/env bash
set -euo pipefail

prompt_file="${OPEN_LAW_LENS_AGENT_PROMPT_FILE:-}"
cache_root="${OPEN_LAW_LENS_CACHE_DIR:-${XDG_CACHE_HOME:-${HOME:-}/.cache}/open-law-lens}"
library_db="${OPEN_LAW_LENS_LIBRARY_DB:-}"
prior_briefs_db="${OPEN_LAW_LENS_PRIOR_BRIEFS_DB:-}"
prior_briefs_dir="${OPEN_LAW_LENS_PRIOR_BRIEFS_DIR:-}"
agent_mode="${OPEN_LAW_LENS_AGENT_MODE:-general}"
workspace="${OPEN_LAW_LENS_AGENT_WORKSPACE:-}"
codex_bin="${CODEX_BIN:-codex}"
codex_profile="${CODEX_PROFILE:-}"
codex_sandbox="${OPEN_LAW_LENS_CODEX_SANDBOX:-workspace-write}"
codex_approval="${OPEN_LAW_LENS_CODEX_APPROVAL:-}"
codex_reasoning="${OPEN_LAW_LENS_CODEX_REASONING_EFFORT:-}"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
workspace_parent="${XDG_CACHE_HOME:-${HOME:-}/.cache}/open-law-lens/agent-workspaces"

if [[ -z "$prompt_file" || ! -f "$prompt_file" ]]; then
  printf 'Open Law Lens agent prompt file not found: %s\n' "$prompt_file" >&2
  exit 2
fi

if [[ -z "$workspace" ]]; then
  mkdir -p "$workspace_parent"
  workspace="$(mktemp -d "$workspace_parent/workspace.XXXXXX")"
else
  mkdir -p "$workspace"
fi

if ! command -v "$codex_bin" >/dev/null 2>&1; then
  printf 'Codex executable not found: %s\n' "$codex_bin" >&2
  exit 127
fi

profile_args=()
if [[ -n "$codex_profile" ]]; then
  profile_args=(--profile "$codex_profile")
fi

case "$codex_sandbox" in
  read-only|workspace-write|danger-full-access) ;;
  *) codex_sandbox="workspace-write" ;;
esac

case "$codex_approval" in
  ""|untrusted|on-request|on-failure|never) ;;
  *) codex_approval="" ;;
esac

case "$codex_reasoning" in
  ""|xhigh) ;;
  *) codex_reasoning="" ;;
esac

approval_args=()
if [[ -n "$codex_approval" ]]; then
  approval_args=(--ask-for-approval "$codex_approval")
fi

reasoning_args=()
if [[ "$codex_reasoning" == "xhigh" ]]; then
  reasoning_args=(-c 'model_reasoning_effort="xhigh"')
fi

cd "$workspace"
mkdir -p "$workspace/tmp"
export TMPDIR="$workspace/tmp"
export OPEN_LAW_LENS_CACHE_DIR="$cache_root"
if [[ -n "$library_db" ]]; then
  export OPEN_LAW_LENS_LIBRARY_DB="$library_db"
fi
if [[ -n "$prior_briefs_db" ]]; then
  export OPEN_LAW_LENS_PRIOR_BRIEFS_DB="$prior_briefs_db"
fi
if [[ -n "$prior_briefs_dir" ]]; then
  export OPEN_LAW_LENS_PRIOR_BRIEFS_DIR="$prior_briefs_dir"
fi

python3 "$script_dir/open-law-lens-codex-agent-pty.py" \
  --prompt-file "$prompt_file" \
  -- \
  "$codex_bin" \
  "${profile_args[@]}" \
  -c 'mcp_servers.openaiDeveloperDocs.enabled=false' \
  -c 'mcp_servers.context7.enabled=false' \
  "${reasoning_args[@]}" \
  -C "$workspace" \
  --sandbox "$codex_sandbox" \
  "${approval_args[@]}"

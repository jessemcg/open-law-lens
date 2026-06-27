#!/usr/bin/env bash
set -euo pipefail

prompt_file="${OPEN_LAW_LENS_AGENT_PROMPT_FILE:-}"
cache_root="${OPEN_LAW_LENS_CACHE_DIR:-${XDG_CACHE_HOME:-${HOME:-}/.cache}/open-law-lens}"
codex_bin="${CODEX_BIN:-codex}"
codex_profile="${CODEX_PROFILE:-}"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
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

profile_args=()
if [[ -n "$codex_profile" ]]; then
  profile_args=(--profile "$codex_profile")
fi

cd "$workspace"
mkdir -p "$workspace/tmp"
export TMPDIR="$workspace/tmp"
export OPEN_LAW_LENS_CACHE_DIR="$cache_root"

python3 "$script_dir/open-law-lens-codex-agent-pty.py" \
  --prompt-file "$prompt_file" \
  -- \
  "$codex_bin" \
  "${profile_args[@]}" \
  -c 'mcp_servers.openaiDeveloperDocs.enabled=false' \
  -c 'mcp_servers.context7.enabled=false' \
  -c 'mcp_servers.courtlistener.command="npx"' \
  -c 'mcp_servers.courtlistener.args=["-y","-p","node@20","-p","mcp-remote@0.1.37","mcp-remote","https://mcp.courtlistener.com","--static-oauth-client-metadata","{\"scope\":\"openid api\"}"]' \
  -c 'mcp_servers.courtlistener.env={MCP_REMOTE_CONFIG_DIR="/home/jesse/.mcp-auth/open-law-lens-courtlistener"}' \
  -c 'mcp_servers.courtlistener.startup_timeout_sec=90' \
  -c 'mcp_servers.courtlistener.enabled=true' \
  -C "$workspace" \
  --sandbox workspace-write

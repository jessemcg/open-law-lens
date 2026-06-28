#!/usr/bin/env bash
set -euo pipefail

prompt_file="${OPEN_LAW_LENS_AGENT_PROMPT_FILE:-}"
cache_root="${OPEN_LAW_LENS_CACHE_DIR:-${XDG_CACHE_HOME:-${HOME:-}/.cache}/open-law-lens}"
agent_mode="${OPEN_LAW_LENS_AGENT_MODE:-general}"
workspace="${OPEN_LAW_LENS_AGENT_WORKSPACE:-}"
codex_bin="${CODEX_BIN:-codex}"
codex_profile="${CODEX_PROFILE:-}"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
workspace_parent="${XDG_CACHE_HOME:-${HOME:-}/.cache}/open-law-lens/agent-workspaces"
project_dir="$(cd -- "$script_dir/.." && pwd)"
mcp_auth_dir="${OPEN_LAW_LENS_MCP_AUTH_DIR:-${MCP_REMOTE_CONFIG_DIR:-$project_dir/.mcp-auth/courtlistener-codex-openid-api}}"

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

cd "$workspace"
mkdir -p "$workspace/tmp"
export TMPDIR="$workspace/tmp"
export OPEN_LAW_LENS_CACHE_DIR="$cache_root"

courtlistener_args=(
  -c 'mcp_servers.courtlistener.command="npx"'
  -c 'mcp_servers.courtlistener.args=["-y","-p","node@20","-p","mcp-remote@0.1.37","mcp-remote","https://mcp.courtlistener.com","--static-oauth-client-metadata","{\"scope\":\"openid api\"}"]'
  -c "mcp_servers.courtlistener.env={MCP_REMOTE_CONFIG_DIR=\"$mcp_auth_dir\"}"
  -c 'mcp_servers.courtlistener.startup_timeout_sec=90'
  -c 'mcp_servers.courtlistener.enabled=true'
)
if [[ "$agent_mode" == "case" ]]; then
  courtlistener_args=(-c 'mcp_servers.courtlistener.enabled=false')
fi

python3 "$script_dir/open-law-lens-codex-agent-pty.py" \
  --prompt-file "$prompt_file" \
  -- \
  "$codex_bin" \
  "${profile_args[@]}" \
  -c 'mcp_servers.openaiDeveloperDocs.enabled=false' \
  -c 'mcp_servers.context7.enabled=false' \
  "${courtlistener_args[@]}" \
  -C "$workspace" \
  --sandbox workspace-write

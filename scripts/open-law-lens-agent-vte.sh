#!/usr/bin/env bash
set -euo pipefail

prompt_file="${OPEN_LAW_LENS_AGENT_PROMPT_FILE:-}"
workspace="${OPEN_LAW_LENS_AGENT_WORKSPACE:-}"
agent_mode="${OPEN_LAW_LENS_AGENT_MODE:-general}"
project_dir="${OPEN_LAW_LENS_PROJECT_DIR:-}"
pi_bin="${OPEN_LAW_LENS_PI_BIN:-pi}"
pi_provider="${OPEN_LAW_LENS_PI_PROVIDER:-}"
pi_model="${OPEN_LAW_LENS_PI_MODEL:-}"
pi_thinking="${OPEN_LAW_LENS_PI_THINKING:-}"
cache_root="${OPEN_LAW_LENS_CACHE_DIR:-${XDG_CACHE_HOME:-${HOME:-}/.cache}/open-law-lens}"
library_db="${OPEN_LAW_LENS_LIBRARY_DB:-}"
prior_briefs_db="${OPEN_LAW_LENS_PRIOR_BRIEFS_DB:-}"
prior_briefs_dir="${OPEN_LAW_LENS_PRIOR_BRIEFS_DIR:-}"

# Resolve uv before doing any model work. Order: validated explicit override,
# then PATH lookup, then the standard user-local install.
uv_bin="${OPEN_LAW_LENS_UV_BIN:-}"
if [[ -n "$uv_bin" ]]; then
  if [[ "$uv_bin" == */* ]]; then
    [[ -x "$uv_bin" ]] || uv_bin=""
  else
    uv_bin="$(command -v "$uv_bin" 2>/dev/null || true)"
  fi
fi
if [[ -z "$uv_bin" ]]; then
  uv_bin="$(command -v uv 2>/dev/null || true)"
fi
if [[ -z "$uv_bin" ]]; then
  if [[ -x "${HOME:-}/.local/bin/uv" ]]; then
    uv_bin="${HOME}/.local/bin/uv"
  fi
fi
if [[ -z "$uv_bin" || ! -x "$uv_bin" ]]; then
  printf 'Open Law Lens requires the uv executable for agent research.\n' >&2
  printf 'Install uv or set OPEN_LAW_LENS_UV_BIN to its full path.\n' >&2
  exit 127
fi
export PATH="$(dirname "$uv_bin"):$PATH"

if [[ -z "$prompt_file" || ! -f "$prompt_file" ]]; then
  printf 'Open Law Lens agent prompt file not found: %s\n' "$prompt_file" >&2
  exit 2
fi
if [[ -z "$workspace" ]]; then
  printf 'Open Law Lens agent workspace is required.\n' >&2
  exit 2
fi
if [[ -z "$project_dir" || ! -f "$project_dir/.pi/settings.json" ]]; then
  printf 'Open Law Lens project Pi settings not found: %s\n' "$project_dir/.pi/settings.json" >&2
  exit 2
fi
if [[ ! -s "$project_dir/.pi/SYSTEM.md" ]]; then
  printf 'Open Law Lens project Pi system prompt not found or empty: %s\n' \
    "$project_dir/.pi/SYSTEM.md" >&2
  exit 2
fi
if [[ ! -x "$pi_bin" ]] && ! command -v "$pi_bin" >/dev/null 2>&1; then
  printf 'Pi executable not found: %s\n' "$pi_bin" >&2
  exit 127
fi
if [[ -n "$pi_provider" || -n "$pi_model" || -n "$pi_thinking" ]]; then
  if [[ -z "$pi_provider" || -z "$pi_model" || -z "$pi_thinking" ]]; then
    printf 'Pi runtime profile requires provider, model, and thinking level.\n' >&2
    exit 2
  fi
  case "$pi_thinking" in
    off|minimal|low|medium|high|xhigh|max) ;;
    *)
      printf 'Unsupported Pi thinking level: %s\n' "$pi_thinking" >&2
      exit 2
      ;;
  esac
fi

pi_path="$pi_bin"
if [[ "$pi_path" != */* ]]; then
  pi_path="$(command -v "$pi_path")"
fi
pi_node="${OPEN_LAW_LENS_PI_NODE_BIN:-}"
pi_candidate="$pi_path"
if [[ -z "$pi_node" ]]; then
  for _attempt in 1 2 3 4; do
    candidate_node="$(dirname "$pi_candidate")/node"
    if [[ -x "$candidate_node" ]]; then
      pi_node="$candidate_node"
      break
    fi
    [[ -L "$pi_candidate" ]] || break
    link_target="$(readlink "$pi_candidate")"
    if [[ "$link_target" == /* ]]; then
      pi_candidate="$link_target"
    else
      pi_candidate="$(dirname "$pi_candidate")/$link_target"
    fi
  done
fi
if [[ -n "$pi_node" ]] \
  && [[ ! -x "$pi_node" ]] \
  && ! command -v "$pi_node" >/dev/null 2>&1; then
  printf 'Pi Node executable not found: %s\n' "$pi_node" >&2
  exit 127
fi

skill="$project_dir/.pi/skills/legal-researcher/SKILL.md"
pi_agent_dir="${PI_CODING_AGENT_DIR:-${HOME:-}/.pi/agent}"
if [[ "$pi_agent_dir" == "~" ]]; then
  pi_agent_dir="${HOME:-}"
elif [[ "$pi_agent_dir" == "~/"* ]]; then
  pi_agent_dir="${HOME:-}/${pi_agent_dir:2}"
fi
extension="${OPEN_LAW_LENS_WEB_ACCESS_EXTENSION:-$pi_agent_dir/npm/node_modules/pi-web-access/index.ts}"
package_json="$(dirname "$extension")/package.json"
if [[ "$agent_mode" == "general" || "$agent_mode" == "appeal" ]]; then
  if [[ ! -f "$skill" ]]; then
    printf 'Legal researcher skill not found: %s\n' "$skill" >&2
    exit 2
  fi
  if [[ ! -f "$extension" || ! -f "$package_json" ]]; then
    printf 'User-level pi-web-access extension not found: %s\n' "$extension" >&2
    printf 'Install it with: pi install npm:pi-web-access\n' >&2
    exit 2
  fi
  if ! grep -Eq '"name"[[:space:]]*:[[:space:]]*"pi-web-access"' "$package_json"; then
    printf 'Expected the pi-web-access package in %s\n' "$package_json" >&2
    exit 2
  fi
fi

mkdir -p "$workspace/tmp" "$workspace/uv-cache" "$workspace/pi-sessions"
mkdir -p "$workspace/.pi"
cp -a "$project_dir/.pi/settings.json" "$workspace/.pi/"
cp -a "$project_dir/.pi/SYSTEM.md" "$workspace/.pi/"
# The mandatory legal-researcher skill is preloaded into the workspace system
# prompt for research modes so Pi starts researching immediately instead of
# spending a turn reading the skill file. Do not copy the skills directory.
if [[ "$agent_mode" == "general" || "$agent_mode" == "appeal" ]]; then
  printf '\n' >> "$workspace/.pi/SYSTEM.md"
  cat "$skill" >> "$workspace/.pi/SYSTEM.md"
fi
export TMPDIR="$workspace/tmp"
export UV_CACHE_DIR="$workspace/uv-cache"
export PI_CODING_AGENT_SESSION_DIR="$workspace/pi-sessions"
export OPEN_LAW_LENS_PROJECT_DIR="$project_dir"
export OPEN_LAW_LENS_CACHE_DIR="$cache_root"
[[ -z "$library_db" ]] || export OPEN_LAW_LENS_LIBRARY_DB="$library_db"
[[ -z "$prior_briefs_db" ]] || export OPEN_LAW_LENS_PRIOR_BRIEFS_DB="$prior_briefs_db"
[[ -z "$prior_briefs_dir" ]] || export OPEN_LAW_LENS_PRIOR_BRIEFS_DIR="$prior_briefs_dir"

prompt="$(<"$prompt_file")"
tools="read,bash,grep,find,ls"
args=(
  --approve
  --no-extensions
)
args+=(
  --no-skills
  --no-prompt-templates
  --no-themes
  --no-context-files
  --system-prompt "$workspace/.pi/SYSTEM.md"
)
if [[ -n "$pi_provider" ]]; then
  args+=(--provider "$pi_provider" --model "$pi_model" --thinking "$pi_thinking")
fi
if [[ "$agent_mode" == "general" || "$agent_mode" == "appeal" ]]; then
  args+=(--extension "$extension")
  tools+=",web_search"
fi
args+=(--tools "$tools")

cd "$workspace"
if [[ -n "$pi_node" ]]; then
  exec "$pi_node" "$pi_path" "${args[@]}" "$prompt"
fi
exec "$pi_path" "${args[@]}" "$prompt"

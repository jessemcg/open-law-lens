#!/usr/bin/env bash
set -euo pipefail

prompt_file="${OPEN_LAW_LENS_AGENT_PROMPT_FILE:-}"
workspace="${OPEN_LAW_LENS_AGENT_WORKSPACE:-}"
agent_mode="${OPEN_LAW_LENS_AGENT_MODE:-general}"
project_dir="${OPEN_LAW_LENS_PROJECT_DIR:-}"
pi_bin="${OPEN_LAW_LENS_PI_BIN:-pi}"
cache_root="${OPEN_LAW_LENS_CACHE_DIR:-${XDG_CACHE_HOME:-${HOME:-}/.cache}/open-law-lens}"
library_db="${OPEN_LAW_LENS_LIBRARY_DB:-}"
prior_briefs_db="${OPEN_LAW_LENS_PRIOR_BRIEFS_DB:-}"
prior_briefs_dir="${OPEN_LAW_LENS_PRIOR_BRIEFS_DIR:-}"

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
if [[ ! -x "$pi_bin" ]] && ! command -v "$pi_bin" >/dev/null 2>&1; then
  printf 'Pi executable not found: %s\n' "$pi_bin" >&2
  exit 127
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
extension="$project_dir/.pi/extensions/pi-web-search/src/index.ts"
package_json="$project_dir/.pi/extensions/pi-web-search/package.json"
if [[ "$agent_mode" == "general" || "$agent_mode" == "appeal" ]]; then
  if [[ ! -f "$skill" ]]; then
    printf 'Legal researcher skill not found: %s\n' "$skill" >&2
    exit 2
  fi
  if [[ ! -f "$extension" || ! -f "$package_json" ]]; then
    printf 'Bundled pi-web-search extension not found: %s\n' "$extension" >&2
    exit 2
  fi
  if ! grep -Eq '"name"[[:space:]]*:[[:space:]]*"pi-web-search"' "$package_json" \
    || ! grep -Eq '"version"[[:space:]]*:[[:space:]]*"1\.3\.1"' "$package_json"; then
    printf 'Expected pi-web-search version 1.3.1 in %s\n' "$package_json" >&2
    exit 2
  fi
fi

mkdir -p "$workspace/tmp" "$workspace/uv-cache" "$workspace/pi-sessions"
mkdir -p "$workspace/.pi"
cp -a "$project_dir/.pi/settings.json" "$workspace/.pi/"
[[ ! -d "$project_dir/.pi/skills" ]] \
  || cp -a "$project_dir/.pi/skills" "$workspace/.pi/"
[[ ! -d "$project_dir/.pi/extensions" ]] \
  || cp -a "$project_dir/.pi/extensions" "$workspace/.pi/"
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
args=(--approve --no-skills --no-extensions)
if [[ "$agent_mode" == "general" || "$agent_mode" == "appeal" ]]; then
  args+=(--skill "$workspace/.pi/skills/legal-researcher/SKILL.md")
  args+=(--extension "$workspace/.pi/extensions/pi-web-search/src/index.ts")
  tools+=",web_search"
  prompt=$'/skill:legal-researcher\n'"$prompt"
fi
args+=(--tools "$tools")

cd "$workspace"
if [[ -n "$pi_node" ]]; then
  exec "$pi_node" "$pi_path" "${args[@]}" "$prompt"
fi
exec "$pi_path" "${args[@]}" "$prompt"

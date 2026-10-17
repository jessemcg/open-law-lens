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

# Installed same-environment entry point; launches never provision dependencies.
umask 077
cli_bin="${OPEN_LAW_LENS_CLI_BIN:-}"
if [[ "$cli_bin" != /* || ! -x "$cli_bin" ]]; then
  printf 'Open Law Lens CLI is unavailable. Relaunch through the provisioned application launcher.\n' >&2
  exit 127
fi
export OPEN_LAW_LENS_CLI_BIN="$cli_bin"

if [[ -z "$prompt_file" || ! -f "$prompt_file" ]]; then
  printf 'Open Law Lens agent prompt file not found: %s\n' "$prompt_file" >&2
  exit 2
fi
if [[ -z "$workspace" ]]; then
  printf 'Open Law Lens agent workspace is required.\n' >&2
  exit 2
fi
if [[ -z "$project_dir" || ! -d "$project_dir/.pi" ]]; then
  printf 'Open Law Lens resources not found: %s\n' "$project_dir" >&2
  exit 2
fi
# Resolve the workflow independently of execution mode (Law and Treatment both
# use general). Fixed resources only: never read skill paths from configuration.
workflow="${OPEN_LAW_LENS_AGENT_PROFILE_KEY:-}"
if [[ -z "$workflow" ]]; then
  case "$agent_mode" in
    general) workflow=law ;;
    case) workflow=research_cache ;;
    brief) workflow=prior_briefs ;;
    appeal) workflow=assess_argument ;;
  esac
fi
case "$agent_mode:$workflow" in
  general:law) workflow_name=law-question ;;
  case:research_cache) workflow_name=research-cache ;;
  brief:prior_briefs) workflow_name=prior-briefs ;;
  appeal:assess_argument) workflow_name=case-assessment ;;
  general:subsequent_treatment) workflow_name=subsequent-treatment ;;
  *)
    printf 'Invalid Open Law Lens mode/workflow pair: %s / %s. Use a supported workflow.\n' "$agent_mode" "$workflow" >&2
    exit 2
    ;;
esac
workflow_skill="$project_dir/.pi/skills/$workflow_name/SKILL.md"
if [[ ! -r "$workflow_skill" || ! -s "$workflow_skill" ]]; then
  printf 'Required Open Law Lens workflow skill unreadable or empty: %s. Restore the app resources.\n' "$workflow_skill" >&2
  exit 2
fi
if [[ ! -r "$project_dir/.pi/SYSTEM.md" || ! -s "$project_dir/.pi/SYSTEM.md" ]]; then
  printf 'Open Law Lens project Pi system prompt not found or empty: %s\n' \
    "$project_dir/.pi/SYSTEM.md" >&2
  exit 2
fi
if [[ -z "${OPEN_LAW_LENS_PI_BIN:-}" ]] && ! command -v pi >/dev/null 2>&1; then
  for candidate in "${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}/bin/pi" "$HOME/.local/bin/pi" "$HOME"/.local/share/pi-node/node-*/bin/pi; do
    if [[ -x "$candidate" ]]; then pi_bin="$candidate"; break; fi
  done
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
if [[ -z "$pi_node" ]]; then
  for candidate in "${XDG_DATA_HOME:-$HOME/.local/share}/pi-node/current/bin/node" "$HOME/.local/share/pi-node/current/bin/node" "$HOME"/.local/share/pi-node/node-*/bin/node; do
    if [[ -x "$candidate" ]]; then pi_node="$candidate"; break; fi
  done
fi
if [[ -n "$pi_node" ]] \
  && [[ ! -x "$pi_node" ]] \
  && ! command -v "$pi_node" >/dev/null 2>&1; then
  printf 'Pi Node executable not found: %s\n' "$pi_node" >&2
  exit 127
fi

# Node readiness and Pi launch argv are separate: official Pi is a shell launcher.
pi_prefix=("$pi_path")
pi_shebang=''
IFS= read -r -n 512 pi_shebang < "$pi_candidate" || true
if [[ -n "$pi_node" ]]; then
  export PATH="$(dirname "$pi_node"):${PATH:-/usr/bin:/bin}"
  if [[ "$pi_shebang" == '#!'*node* ]] || { [[ "$pi_shebang" != '#!'* ]] && [[ "$pi_candidate" == *.js || "$pi_candidate" == *.mjs || "$pi_candidate" == *.cjs ]]; }; then
    pi_prefix=("$pi_node" "$pi_path")
  fi
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
  if [[ ! -r "$skill" || ! -s "$skill" ]]; then
    printf 'Legal researcher skill unreadable or empty: %s. Restore the app resources.\n' "$skill" >&2
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
  # Computer Use is optional: extraction reports unavailable recovery safely.
fi

mkdir -p "$workspace/tmp" "$workspace/uv-cache" "$workspace/pi-sessions"
mkdir -p "$workspace/.pi"
settings_file="${OPEN_LAW_LENS_PI_SETTINGS:-$project_dir/.pi/settings.json}"
if [[ "${OPEN_LAW_LENS_STORAGE:-legacy}" == standalone ]]; then
  settings_file="${OPEN_LAW_LENS_PI_SETTINGS:-${XDG_CONFIG_HOME:-$HOME/.config}/open-law-lens/pi/settings.json}"
fi
if [[ -f "$settings_file" ]]; then
  cp -- "$settings_file" "$workspace/.pi/settings.json"
elif [[ "${OPEN_LAW_LENS_STORAGE:-legacy}" == standalone ]]; then
  printf '{}\n' > "$workspace/.pi/settings.json"
else
  printf 'Maintained Open Law Lens Pi settings missing. Restore the selected app preferences.\n' >&2
  exit 2
fi
cp -a "$project_dir/.pi/SYSTEM.md" "$workspace/.pi/"
# The live follow-up bridge is explicitly staged and loaded only when present;
# it registers no model-facing tools and never widens the tool allowlist.
followup_args=()
bridge_extension="$project_dir/.pi/extensions/open-law-lens-followup-bridge.ts"
if [[ -f "$bridge_extension" ]]; then
  mkdir -p "$workspace/.pi/extensions"
  cp -a "$bridge_extension" "$workspace/.pi/extensions/"
  followup_args=(--extension "$workspace/.pi/extensions/open-law-lens-followup-bridge.ts")
fi
# Rebuilt from the shared base above on EVERY launch, including reused workspaces.
# Preload all required instructions; no skill discovery or model turn is needed.
if [[ "$agent_mode" == "general" || "$agent_mode" == "appeal" ]]; then
  printf '\n' >> "$workspace/.pi/SYSTEM.md"
  cat "$skill" >> "$workspace/.pi/SYSTEM.md"
fi
printf '\n' >> "$workspace/.pi/SYSTEM.md"
cat "$workflow_skill" >> "$workspace/.pi/SYSTEM.md"
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
args+=("${followup_args[@]}")
# Passive observer for every Pi-backed mode; never grant extra model tools.
metrics_project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
metrics_prefix=("${pi_prefix[@]}")
metrics_values=()
helper="$metrics_project_root/../PiRunMetrics/launch_adapter.py"
metrics_enabled="${PI_RUN_METRICS_ENABLED:-}"
if [[ -z "$metrics_enabled" ]]; then
  if [[ "${OPEN_LAW_LENS_STORAGE:-legacy}" == standalone ]]; then metrics_enabled=0; else metrics_enabled=1; fi
fi
if [[ "${OPEN_LAW_LENS_STORAGE:-legacy}" == standalone && "$metrics_enabled" != 0 ]]; then
  export PI_RUN_METRICS_ROOT="${PI_RUN_METRICS_ROOT:-${XDG_STATE_HOME:-$HOME/.local/state}/open-law-lens/run-metrics/runs}"
fi
if [[ "$metrics_enabled" != 0 && -r "$helper" && -x /usr/bin/python3 ]]; then
  mapfile -d '' -t metrics_values < <(/usr/bin/python3 "$helper" --shell \
    --project "$metrics_project_root" --app open-law-lens --workflow "$workflow" -- "${metrics_prefix[@]}")
fi
if (( ${#metrics_values[@]} )); then
  [[ -z "${metrics_values[0]}" ]] || args+=(--extension "${metrics_values[0]}")
  for entry in "${metrics_values[@]:1}"; do export "$entry"; done
else
  unset PI_RUN_METRICS_APP PI_RUN_METRICS_WORKFLOW PI_RUN_METRICS_REVISION PI_RUN_METRICS_DIRTY PI_RUN_METRICS_PI_VERSION PI_RUN_METRICS_BUILD_PROVENANCE PI_RUN_METRICS_LAUNCH_CONFIGURATION
  if [[ "$metrics_enabled" != 0 ]]; then
    printf 'Pi run metrics: collection incomplete or unavailable.\n' >&2
  fi
fi
args+=(--tools "$tools")

cd "$workspace"
exec "${pi_prefix[@]}" "${args[@]}" "$prompt"

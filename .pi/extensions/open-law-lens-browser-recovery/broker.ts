/**
 * Pure, framework-free policy logic for the default-browser Scholar recovery
 * bridge. This module has no Pi or pi-mcp-adapter imports so it can be unit
 * tested with plain `node --test`. Everything here is deliberately side-effect
 * free except for the small `BrokerState` mutation helpers below.
 */

export const SERVER_NAME = "computer_use_linux";

/** The only computer-use tools the bridge exposes, in original (unprefixed) form. */
export const ALLOWED_TOOLS: ReadonlySet<string> = new Set([
  "doctor",
  "list_windows",
  "focused_window",
  "get_app_state",
  "perform_action",
  "press_key",
]);

/** Tools whose invocation changes desktop state and therefore needs a fresh observation. */
export const MUTATING_TOOLS: ReadonlySet<string> = new Set([
  "perform_action",
  "press_key",
]);

/** The only key chords permitted through the bridge. */
export const ALLOWED_PRESS_KEYS: ReadonlySet<string> = new Set(["ctrl+a", "ctrl+c"]);

/** Upper bound on `get_app_state` nodes to avoid flooding model context. */
export const MAX_GET_APP_STATE_NODES = 1000;

/**
 * Keep the bounded accessibility tree available inside mcpScript for filtering.
 * Model-facing MCP output remains guarded at the adapter defaults; only the
 * extension-local details payload is raised above Firefox's roughly 400 KiB
 * 1,000-node tree. This avoids spilling the tree to a file that the confined
 * script worker cannot read.
 */
export const MCP_DETAILS_MAX_BYTES = 2 * 1024 * 1024;

export interface AuthorizedWindow {
  windowId: number;
  title: string;
  url: string;
}

export interface BrokerState {
  authorized: AuthorizedWindow | null;
  fresh: boolean;
}

export function initialBrokerState(): BrokerState {
  return { authorized: null, fresh: false };
}

export type BrokerDecision = "allow_once" | "deny";

export function normalizeKey(key: unknown): string {
  if (typeof key !== "string") return "";
  // The key grammar treats '+' as the combo separator and ignores spaces and
  // hyphens; normalize hyphens to '+' so "Ctrl-A", "Ctrl A", and "Ctrl+A"
  // all collapse to the same canonical "ctrl+a".
  return key.toLowerCase().replace(/\s+/g, "").replace(/-/g, "+");
}

export function isScholarUrl(url: unknown): boolean {
  if (typeof url !== "string" || !url) return false;
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== "https:") return false;
    const host = parsed.hostname.toLowerCase();
    return host === "scholar.google.com" || host.endsWith(".scholar.google.com");
  } catch {
    return false;
  }
}

/**
 * Authorize a window for mutating controls. Accepts only an observed
 * `scholar.google.com` URL and a non-empty Scholar page title. Re-authorizing
 * replaces any prior authorized window.
 */
export function authorizeWindow(
  state: BrokerState,
  windowId: unknown,
  title: unknown,
  url: unknown,
): string {
  if (typeof windowId !== "number" || !Number.isFinite(windowId)) {
    return "window_id must be a finite number.";
  }
  if (!isScholarUrl(url)) {
    return "url must be an https scholar.google.com URL.";
  }
  if (typeof title !== "string" || !title.trim()) {
    return "title must be a non-empty Scholar page title.";
  }
  state.authorized = { windowId, title: title.trim(), url: String(url) };
  state.fresh = false;
  return "";
}

function hasTruthy(args: Record<string, unknown>, ...keys: string[]): boolean {
  return keys.some((key) => {
    const value = args[key];
    return value !== undefined && value !== null && value !== "" && value !== false;
  });
}

/**
 * Decide whether a single computer-use tool call may proceed. Mutating calls
 * require an authorized window plus a fresh observation and, on success,
 * consume the freshness token so the model must re-observe before the next
 * mutation. Everything outside the allowlist is denied.
 */
export function decideTool(
  state: BrokerState,
  originalToolName: string,
  args: Record<string, unknown> | undefined,
): BrokerDecision {
  const tool = originalToolName;
  const a = args ?? {};

  if (!ALLOWED_TOOLS.has(tool)) return "deny";

  if (tool === "doctor" || tool === "list_windows" || tool === "focused_window") {
    return "allow_once";
  }

  if (tool === "get_app_state") {
    const windowId = a.window_id;
    if (typeof windowId !== "number" || !Number.isFinite(windowId)) return "deny";
    if (a.include_screenshot === true) return "deny";
    if (hasTruthy(a, "app_id")) return "deny";
    const maxNodes = a.max_nodes;
    if (
      typeof maxNodes !== "number"
      || !Number.isFinite(maxNodes)
      || maxNodes <= 0
      || maxNodes > MAX_GET_APP_STATE_NODES
    ) {
      return "deny";
    }
    if (state.authorized && windowId === state.authorized.windowId) {
      state.fresh = true;
    }
    return "allow_once";
  }

  if (tool === "perform_action") {
    if (!state.authorized || !state.fresh) return "deny";
    const index = a.element_index;
    if (typeof index !== "number" || !Number.isFinite(index)) return "deny";
    if (hasTruthy(a, "action", "element_identifier", "name", "role", "text")) return "deny";
    state.fresh = false;
    return "allow_once";
  }

  if (tool === "press_key") {
    if (!state.authorized || !state.fresh) return "deny";
    const windowId = a.window_id;
    if (
      typeof windowId !== "number"
      || !Number.isFinite(windowId)
      || windowId !== state.authorized.windowId
    ) {
      return "deny";
    }
    if (!ALLOWED_PRESS_KEYS.has(normalizeKey(a.key))) return "deny";
    state.fresh = false;
    return "allow_once";
  }

  return "deny";
}

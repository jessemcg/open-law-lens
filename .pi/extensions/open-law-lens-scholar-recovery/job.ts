/**
 * Pure, framework-free logic for the Open Law Lens confined default-browser
 * Scholar recovery job. This module has no Pi or Node-filesystem imports so it
 * can be unit tested with plain `node --test`.
 *
 * The job is the *only* non-baseline official-copy path. It exposes two fixed
 * tools:
 *
 *  - `open_law_lens_launch_scholar_query`: launches the environment-bound
 *    request query through `uv ... open-scholar-browser` using argv execution
 *    (never a shell), and rejects any query differing from the bound request.
 *  - `open_law_lens_complete_scholar_recovery`: a one-shot atomic result
 *    writer for the machine-readable recovery result.
 */

export const RESULT_VERSION = 1;
export const VALID_OUTCOMES = ["copied", "not_found", "blocked", "failed"] as const;
export type RecoveryOutcome = (typeof VALID_OUTCOMES)[number];

const SCHOLAR_HOST = "scholar.google.com";

/** A qualifying result URL must be an https Scholar *case* page. */
export function isScholarCaseUrl(url: unknown): boolean {
  if (typeof url !== "string" || !url) return false;
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== "https:") return false;
    const host = parsed.hostname.toLowerCase();
    if (host !== SCHOLAR_HOST && !host.endsWith("." + SCHOLAR_HOST)) return false;
    if (!parsed.pathname.startsWith("/scholar_case")) return false;
    return true;
  } catch {
    return false;
  }
}

export function normalizeQuery(value: unknown): string {
  return typeof value === "string" ? value.replace(/\s+/g, " ").trim() : "";
}

/**
 * Validate the launch tool's query against the environment-bound request. Empty
 * strings describe *why* validation failed; a non-empty binding or an empty
 * return means success.
 */
export function launchQueryError(boundQuery: unknown, suppliedQuery: unknown): string {
  const bound = normalizeQuery(boundQuery);
  const supplied = normalizeQuery(suppliedQuery);
  if (!bound) return "No bound Scholar recovery query is configured for this job.";
  if (!supplied) return "A Scholar query is required.";
  if (supplied.toLowerCase() !== bound.toLowerCase()) {
    return "The supplied query does not match the environment-bound recovery query.";
  }
  return "";
}

/** Build the argv executed to open Scholar in the current default browser. */
export function buildLaunchCommand(
  query: string,
  projectDir: string,
  uvBin: string,
): { command: string; args: string[] } {
  return {
    command: uvBin || "uv",
    args: [
      "run",
      "--project",
      projectDir,
      "--no-sync",
      "open-law-lens",
      "open-scholar-browser",
      query,
    ],
  };
}

export interface CompletionInput {
  outcome?: unknown;
  query?: unknown;
  source_url?: unknown;
  message?: unknown;
}

/** Validate the completion tool's inputs; returns an error string or null. */
export function completionError(input: CompletionInput): string | null {
  const outcome = typeof input.outcome === "string" ? input.outcome : "";
  if (!VALID_OUTCOMES.includes(outcome as RecoveryOutcome)) {
    return "outcome must be one of copied, not_found, blocked, or failed.";
  }
  const message =
    typeof input.message === "string" ? input.message.replace(/\s+/g, " ").trim() : "";
  if (!message) return "message is required.";
  if (outcome === "copied") {
    const url = typeof input.source_url === "string" ? input.source_url.trim() : "";
    if (!url || !isScholarCaseUrl(url)) {
      return "source_url must be an https scholar.google.com/scholar_case URL when outcome is copied.";
    }
  }
  return null;
}

/** Normalize the completion inputs into the machine-readable result payload. */
export function buildResult(input: CompletionInput): object {
  const outcome = input.outcome as RecoveryOutcome;
  const query = normalizeQuery(input.query);
  const source_url =
    outcome === "copied" && typeof input.source_url === "string"
      ? input.source_url.trim()
      : "";
  const message =
    typeof input.message === "string" ? input.message.replace(/\s+/g, " ").trim() : "";
  return {
    version: RESULT_VERSION,
    outcome,
    query,
    source_url,
    message,
  };
}

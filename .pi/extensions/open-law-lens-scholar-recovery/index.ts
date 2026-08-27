/**
 * Open Law Lens confined default-browser Scholar recovery job extension.
 *
 * This first-party OpenLawLens-only extension is separate from the shared
 * browser-recovery safety bridge. It exposes exactly two fixed tools:
 *
 *  - `open_law_lens_launch_scholar_query`: opens Scholar in the current default
 *    HTTPS browser for the environment-bound request query, using `uv` argv
 *    execution (never a shell), and rejects any differing query.
 *  - `open_law_lens_complete_scholar_recovery`: a one-shot atomic writer for
 *    the machine-readable recovery result (private 0600 permissions; no opinion
 *    or clipboard text is logged).
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type, type Static } from "typebox";
import { spawn } from "node:child_process";
import { rename, stat, writeFile } from "node:fs/promises";
import { env } from "node:process";

import {
  buildLaunchCommand,
  buildResult,
  completionError,
  launchQueryError,
  normalizeQuery,
} from "./job.ts";

const BOUND_QUERY_ENV = "OPEN_LAW_LENS_SCHOLAR_QUERY";
const RESULT_PATH_ENV = "OPEN_LAW_LENS_SCHOLAR_RESULT_PATH";
const PROJECT_DIR_ENV = "OPEN_LAW_LENS_PROJECT_DIR";
const UV_BIN_ENV = "OPEN_LAW_LENS_UV_BIN";

const LaunchSchema = Type.Object({
  query: Type.String({ description: "The exact request query to open in Scholar." }),
});
type LaunchParams = Static<typeof LaunchSchema>;

const CompleteSchema = Type.Object({
  outcome: Type.String({ description: "copied | not_found | blocked | failed" }),
  query: Type.String({ description: "The request query this result corresponds to." }),
  source_url: Type.Optional(
    Type.String({ description: "Scholar case URL, required only when outcome is copied." })
  ),
  message: Type.String({ description: "Concise user-facing detail." }),
});
type CompleteParams = Static<typeof CompleteSchema>;

function boundQuery(): string {
  return normalizeQuery(env[BOUND_QUERY_ENV]);
}

function resultPath(): string {
  return (env[RESULT_PATH_ENV] ?? "").trim();
}

function projectDir(): string {
  return (env[PROJECT_DIR_ENV] ?? "").trim();
}

function uvBin(): string {
  return (env[UV_BIN_ENV] ?? "").trim() || "uv";
}

function launchBrowser(query: string): Promise<{ ok: boolean; message: string }> {
  return new Promise((resolve) => {
    const dir = projectDir();
    if (!dir) {
      resolve({ ok: false, message: "OPEN_LAW_LENS_PROJECT_DIR is not set for this job." });
      return;
    }
    const { command, args } = buildLaunchCommand(query, dir, uvBin());
    let settled = false;
    const child = spawn(command, args, { stdio: "ignore", detached: true });
    child.once("error", (error: NodeJS.ErrnoException) => {
      if (settled) return;
      settled = true;
      resolve({ ok: false, message: `Failed to launch open-scholar-browser: ${error.message}` });
    });
    child.once("spawn", () => {
      if (settled) return;
      settled = true;
      // Let the browser outlive this tool call; the bridge observes it next.
      child.unref();
      resolve({
        ok: true,
        message: `Opened Google Scholar search for ${query} in the current default browser.`,
      });
    });
  });
}

async function writeResultOnce(path: string, payload: object): Promise<{ ok: boolean; message: string }> {
  if (!path) {
    return { ok: false, message: "OPEN_LAW_LENS_SCHOLAR_RESULT_PATH is not set for this job." };
  }
  try {
    await stat(path);
    return { ok: false, message: "A recovery result has already been written for this job." };
  } catch {
    // Not yet written; proceed.
  }
  const tmp = `${path}.${process.pid}.tmp`;
  try {
    await writeFile(tmp, JSON.stringify(payload, null, 2) + "\n", {
      encoding: "utf8",
      mode: 0o600,
    });
    await rename(tmp, path);
    return { ok: true, message: "Recorded recovery result." };
  } catch (error) {
    return {
      ok: false,
      message: `Failed to write recovery result: ${error instanceof Error ? error.message : String(error)}`,
    };
  }
}

export default async function (pi: ExtensionAPI) {
  await pi.registerTool({
    name: "open_law_lens_launch_scholar_query",
    label: "Launch Scholar Query",
    description:
      "Open Google Scholar in the current default HTTPS browser for the environment-bound " +
      "recovery query. Rejects any query that differs from the bound request. Launches through " +
      "`uv ... open-scholar-browser` using argv execution, never a shell.",
    parameters: LaunchSchema,
    async execute(_toolCallId: string, params: LaunchParams) {
      const error = launchQueryError(boundQuery(), params.query);
      if (error) {
        return { content: [{ type: "text" as const, text: error }], isError: true };
      }
      const result = await launchBrowser(normalizeQuery(params.query));
      return {
        content: [{ type: "text" as const, text: result.message }],
        isError: !result.ok,
      };
    },
  });

  await pi.registerTool({
    name: "open_law_lens_complete_scholar_recovery",
    label: "Complete Scholar Recovery",
    description:
      "Write the one-shot, machine-readable default-browser Scholar recovery result. " +
      "Source URL is required only for outcome 'copied' and must be a Scholar case URL. " +
      "No opinion or clipboard text is recorded.",
    parameters: CompleteSchema,
    async execute(_toolCallId: string, params: CompleteParams) {
      const error = completionError(params);
      if (error) {
        return { content: [{ type: "text" as const, text: error }], isError: true };
      }
      const result = await writeResultOnce(resultPath(), buildResult(params));
      return {
        content: [{ type: "text" as const, text: result.message }],
        isError: !result.ok,
      };
    },
  });
}

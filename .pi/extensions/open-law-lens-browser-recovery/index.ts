/**
 * Open Law Lens default-browser Google Scholar recovery bridge.
 *
 * This first-party extension installs a *confined* pi-mcp-adapter instance
 * whose only MCP server is the user-installed computer-use-linux server, and
 * then brokers every desktop-control call through a small authorization
 * state machine. It never merges or discovers ambient/global MCP servers.
 *
 * The compatible package versions exercised by this bridge are
 * `pi-mcp-adapter` 2.29.0 and `@agent-sh/computer-use-linux` 0.4.9.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type, type Static } from "typebox";
import { homedir } from "node:os";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { env, execPath } from "node:process";

import {
  ALLOWED_TOOLS,
  MAX_GET_APP_STATE_NODES,
  MCP_DETAILS_MAX_BYTES,
  SERVER_NAME,
  authorizeWindow,
  decideTool,
  initialBrokerState,
  type BrokerState,
} from "./broker.ts";

/** Event channel pi-mcp-adapter emits on `pi.events` before each MCP tool call. */
const MCP_TOOL_APPROVAL_REQUEST_EVENT = "pi-mcp-adapter:tool-approval-request";

const AUTHORIZE_TOOL = "open_law_lens_authorize_scholar_window";

const FORBIDDEN_TOOLS = [
  "screenshot",
  "click",
  "type_text",
  "scroll",
  "drag",
  "set_value",
  "move_window",
  "resize_window",
  "activate_window",
  "list_apps",
  "setup_accessibility",
  "setup_window_targeting",
];

const AuthorizeSchema = Type.Object({
  window_id: Type.Number({ description: "Exact compositor window id to authorize (from list_windows/focused_window)." }),
  title: Type.String({ description: "Observed window title, which must be a Scholar page title." }),
  url: Type.String({ description: "Observed scholar.google.com URL in that window." }),
});
type AuthorizeParams = Static<typeof AuthorizeSchema>;

function resolveAgentDir(): string {
  const configured = env.PI_CODING_AGENT_DIR?.trim();
  if (configured) {
    if (configured === "~") return homedir();
    if (configured.startsWith("~/")) return join(homedir(), configured.slice(2));
    return configured;
  }
  return join(homedir(), ".pi", "agent");
}

interface ApprovalRequest {
  serverName?: unknown;
  originalToolName?: unknown;
  prefixedToolName?: unknown;
  args?: unknown;
  claim?: (handler: () => string) => boolean;
}

function isApprovalRequest(value: unknown): value is ApprovalRequest {
  return typeof value === "object" && value !== null;
}

export default async function (pi: ExtensionAPI) {
  const agentDir = resolveAgentDir();
  const adapterEntry = join(agentDir, "npm", "node_modules", "pi-mcp-adapter", "index.ts");
  const computerUseLinuxJs = join(
    agentDir,
    "npm",
    "node_modules",
    "@agent-sh",
    "computer-use-linux",
    "npm",
    "bin",
    "computer-use-linux.js",
  );

  if (!existsSync(adapterEntry)) {
    throw new Error(
      `pi-mcp-adapter not found at ${adapterEntry}. ` +
        `Install it with: pi install npm:pi-mcp-adapter`,
    );
  }
  if (!existsSync(computerUseLinuxJs)) {
    throw new Error(
      `@agent-sh/computer-use-linux wrapper not found at ${computerUseLinuxJs}. ` +
        `Install it with: pi install npm:@agent-sh/computer-use-linux`,
    );
  }

  // Load `createMcpAdapter` from the user-installed package. This dynamic
  // import is resolved through Pi's extension loader (jiti), so the adapter's
  // own peer imports resolve against Pi's bundled modules exactly as they do
  // when pi-mcp-adapter is loaded as a normal user extension.
  const { createMcpAdapter } = await import(adapterEntry);

  const state: BrokerState = initialBrokerState();

  // Install the adapter with an in-memory config containing only the one
  // confined server. No ambient/global MCP discovery happens here.
  const installAdapter = createMcpAdapter({
    config: {
      mcpServers: {
        [SERVER_NAME]: {
          command: execPath,
          args: [computerUseLinuxJs, "mcp"],
          includeTools: [...ALLOWED_TOOLS],
          excludeTools: FORBIDDEN_TOOLS,
          directTools: [...ALLOWED_TOOLS],
          toolPrefix: "server",
          lifecycle: "lazy",
        },
      },
      settings: {
        scriptMode: true,
        sampling: false,
        elicitation: false,
        disableProxyTool: false,
        outputGuard: {
          // Keep the bounded tree available only to mcpScript. Model-facing
          // output retains the adapter's normal 50 KiB / 2,000-line caps.
          detailsMaxBytes: MCP_DETAILS_MAX_BYTES,
        },
      },
    },
  });
  installAdapter(pi);

  pi.registerTool({
    name: AUTHORIZE_TOOL,
    label: "Authorize Scholar Window",
    description:
      "Authorize a specific Google Scholar browser window for desktop-control recovery. " +
      "Accepts only a window id actually observed through list_windows/focused_window/get_app_state, " +
      "together with its observed scholar.google.com URL and Scholar page title. " +
      "Call this exactly once per window before any perform_action or press_key.",
    parameters: AuthorizeSchema,
    async execute(
      _toolCallId: string,
      params: AuthorizeParams,
      _signal: AbortSignal | undefined,
      _onUpdate: unknown,
      _ctx: unknown,
    ) {
      const error = authorizeWindow(state, params.window_id, params.title, params.url);
      if (error) {
        return {
          content: [{ type: "text" as const, text: error }],
          isError: true,
        };
      }
      return {
        content: [
          {
            type: "text" as const,
            text: `Authorized Scholar window ${params.window_id}. Observe it again with get_app_state before mutating controls.`,
          },
        ],
      };
    },
  });

  // Broker every MCP tool call that passes through the adapter. The claim must
  // happen synchronously inside the event emission, so we register a handler
  // that claims immediately and defers the actual decision to `decideTool`.
  pi.events.on(MCP_TOOL_APPROVAL_REQUEST_EVENT, (raw: unknown) => {
    if (!isApprovalRequest(raw)) return;
    if (raw.serverName !== SERVER_NAME) return;
    if (typeof raw.originalToolName !== "string") return;
    const decision = decideTool(
      state,
      raw.originalToolName,
      typeof raw.args === "object" && raw.args !== null
        ? (raw.args as Record<string, unknown>)
        : undefined,
    );
    if (typeof raw.claim === "function") {
      raw.claim(() => decision);
    }
  });

  // Reset session-local authorization at the start of every session.
  pi.on("session_start", () => {
    state.authorized = null;
    state.fresh = false;
  });
}

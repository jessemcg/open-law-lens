/**
 * Open Law Lens live Agent follow-up bridge (protocol v1).
 *
 * Starts a private Unix-domain socket server for the lifetime of one Pi
 * session and forwards literal user text to the live conversation through
 * `pi.sendUserMessage(text, { expandPromptTemplates: false })`. It registers
 * no model-facing tools and never reads transcripts, prompts, or credentials.
 *
 * Environment:
 *   OPEN_LAW_LENS_AGENT_FOLLOWUP_SOCKET       absolute socket path under the runtime dir
 *   OPEN_LAW_LENS_AGENT_FOLLOWUP_TOKEN        random session token
 *   OPEN_LAW_LENS_AGENT_FOLLOWUP_RUNTIME_DIR  application-owned private directory (0700)
 */

import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { timingSafeEqual } from "node:crypto";
import { chmod, lstat, mkdir, realpath, rm } from "node:fs/promises";
import { createServer, type Server, type Socket } from "node:net";
import { dirname, isAbsolute, relative, resolve } from "node:path";

const PROTOCOL_VERSION = 1;
const MAX_TEXT_BYTES = 64 * 1024;
const MAX_FRAME_BYTES = 128 * 1024;
const MAX_REMEMBERED_REQUESTS = 256;
const TOKEN_RE = /^[A-Za-z0-9_-]{24,128}$/;
const REQUEST_ID_RE = /^[A-Za-z0-9_-]{8,64}$/;

type BridgeState = "starting" | "busy" | "ready" | "closed";

function inside(child: string, parent: string): boolean {
  const rel = relative(parent, child);
  return rel === "" || (!rel.startsWith("..") && !isAbsolute(rel));
}

function safeEqual(left: string, right: string): boolean {
  const a = Buffer.from(left, "utf8");
  const b = Buffer.from(right, "utf8");
  if (a.length !== b.length) return false;
  return timingSafeEqual(a, b);
}

function isOwnedByCurrentUser(fileStat: { uid: number }): boolean {
  return typeof process.getuid !== "function" || fileStat.uid === process.getuid();
}

export default function openLawLensFollowupBridge(pi: ExtensionAPI) {
  const socketPathRaw = (process.env.OPEN_LAW_LENS_AGENT_FOLLOWUP_SOCKET ?? "").trim();
  const runtimeDirRaw = (process.env.OPEN_LAW_LENS_AGENT_FOLLOWUP_RUNTIME_DIR ?? "").trim();
  const token = process.env.OPEN_LAW_LENS_AGENT_FOLLOWUP_TOKEN ?? "";

  let server: Server | null = null;
  let state: BridgeState = "starting";
  let transportError = "";
  let latestCtx: ExtensionContext | undefined;
  let inFlightRequestId: string | null = null;
  const remembered = new Map<string, true>();

  function remember(requestId: string): void {
    if (remembered.size >= MAX_REMEMBERED_REQUESTS) {
      const oldest = remembered.keys().next().value;
      if (oldest !== undefined) remembered.delete(oldest);
    }
    remembered.set(requestId, true);
  }

  function response(
    type: string,
    id: string,
    body: Record<string, unknown>,
  ): string {
    return `${JSON.stringify({ v: PROTOCOL_VERSION, type, id, ...body })}\n`;
  }

  function writeResponse(socket: Socket, payload: string): void {
    try {
      socket.write(payload);
    } catch {
      // The peer went away; nothing to recover.
    }
  }

  function fail(
    socket: Socket,
    type: string,
    id: string,
    error: string,
    httpState: BridgeState = state,
  ): void {
    writeResponse(socket, response(type, id, { ok: false, error, state: httpState }));
  }

  async function unlinkOwnedSocket(socketPath: string, runtimeDir: string): Promise<void> {
    try {
      const fileStat = await lstat(socketPath);
      if (!fileStat.isSocket() || !isOwnedByCurrentUser(fileStat)) return;
      if (!inside(await realpath(socketPath), await realpath(runtimeDir))) return;
      await rm(socketPath, { force: true });
    } catch {
      // Missing or replaced; leave it alone.
    }
  }

  async function handleFrame(socket: Socket, line: string): Promise<void> {
    let payload: unknown;
    try {
      payload = JSON.parse(line);
    } catch {
      fail(socket, "status", "", "invalid_request");
      return;
    }
    if (!payload || typeof payload !== "object") {
      fail(socket, "status", "", "invalid_request");
      return;
    }
    const request = payload as Record<string, unknown>;
    const type = request.type === "submit" ? "submit" : request.type === "status" ? "status" : "";
    const id = typeof request.id === "string" && REQUEST_ID_RE.test(request.id) ? request.id : "";
    if (!type || !id || request.v !== PROTOCOL_VERSION) {
      fail(socket, type || "status", id, request.v !== PROTOCOL_VERSION ? "bad_version" : "invalid_request");
      return;
    }
    if (typeof request.token !== "string" || !safeEqual(request.token, token)) {
      fail(socket, type, id, "unauthorized", "closed");
      return;
    }
    if (!server) {
      fail(socket, type, id, "unavailable", "closed");
      return;
    }
    if (type === "status") {
      writeResponse(socket, response("status", id, { ok: true, state }));
      return;
    }

    const text = typeof request.text === "string" ? request.text.trim() : "";
    if (!text) {
      fail(socket, "submit", id, "invalid_request");
      return;
    }
    if (Buffer.byteLength(text, "utf8") > MAX_TEXT_BYTES) {
      fail(socket, "submit", id, "too_large");
      return;
    }
    if (remembered.has(id)) {
      writeResponse(socket, response("submit", id, { ok: true, state, duplicate: true }));
      return;
    }
    if (inFlightRequestId !== null || !latestCtx || !latestCtx.isIdle()) {
      fail(socket, "submit", id, "busy", "busy");
      return;
    }

    inFlightRequestId = id;
    remember(id);
    state = "busy";
    try {
      pi.sendUserMessage(text, { expandPromptTemplates: false });
    } catch (error) {
      inFlightRequestId = null;
      if (server) state = "ready";
      fail(socket, "submit", id, "rejected", state);
      return;
    }
    writeResponse(socket, response("submit", id, { ok: true, state: "busy", duplicate: false }));
  }

  function handleConnection(socket: Socket): void {
    socket.setTimeout(5000, () => socket.destroy());
    const chunks: Buffer[] = [];
    let size = 0;
    let handled = false;
    socket.on("data", (data: Buffer) => {
      if (handled) return;
      size += data.length;
      if (size > MAX_FRAME_BYTES) {
        handled = true;
        fail(socket, "status", "", "too_large");
        socket.end();
        return;
      }
      chunks.push(data);
      const buffer = Buffer.concat(chunks);
      const newline = buffer.indexOf(0x0a);
      if (newline < 0) return;
      handled = true;
      void handleFrame(socket, buffer.subarray(0, newline).toString("utf8")).finally(
        () => socket.end(),
      );
    });
    socket.on("error", () => undefined);
  }

  async function startServer(): Promise<void> {
    if (server || transportError) return;
    if (!socketPathRaw || !runtimeDirRaw || !TOKEN_RE.test(token)) {
      transportError = "follow-up bridge environment is incomplete";
      state = "closed";
      return;
    }
    try {
      const socketPath = resolve(socketPathRaw);
      const runtimeDir = resolve(runtimeDirRaw);
      if (!isAbsolute(socketPathRaw) || !isAbsolute(runtimeDirRaw) || !inside(socketPath, runtimeDir)) {
        throw new Error("follow-up socket is outside the runtime directory");
      }
      await mkdir(runtimeDir, { recursive: true, mode: 0o700 });
      await chmod(runtimeDir, 0o700);
      const runtimeStat = await lstat(runtimeDir);
      if (!runtimeStat.isDirectory() || !isOwnedByCurrentUser(runtimeStat)) {
        throw new Error("follow-up runtime directory is not owned");
      }
      await unlinkOwnedSocket(socketPath, runtimeDir);
      const created = createServer(handleConnection);
      created.on("error", () => {
        transportError = "follow-up bridge server failed";
      });
      await new Promise<void>((resolvePromise, rejectPromise) => {
        created.once("error", rejectPromise);
        created.listen(socketPath, () => {
          created.off("error", rejectPromise);
          resolvePromise();
        });
      });
      await chmod(socketPath, 0o600);
      server = created;
      state = "starting";
    } catch (error: any) {
      transportError = error?.message || "follow-up bridge failed to start";
      state = "closed";
    }
  }

  async function stopServer(): Promise<void> {
    const current = server;
    server = null;
    state = "closed";
    inFlightRequestId = null;
    if (current) {
      await new Promise<void>((resolvePromise) => current.close(() => resolvePromise()));
    }
    if (socketPathRaw && runtimeDirRaw) {
      await unlinkOwnedSocket(resolve(socketPathRaw), resolve(runtimeDirRaw));
    }
  }

  pi.on("session_start", async (_event, ctx) => {
    latestCtx = ctx;
    await startServer();
  });

  pi.on("session_shutdown", async () => {
    await stopServer();
  });

  pi.on("before_agent_start", (_event, ctx) => {
    latestCtx = ctx;
    if (server) state = "busy";
  });

  pi.on("agent_start", (_event, ctx) => {
    latestCtx = ctx;
    if (server) state = "busy";
  });

  pi.on("agent_settled", (_event, ctx) => {
    latestCtx = ctx;
    inFlightRequestId = null;
    if (server) state = "ready";
  });
}

/**
 * Assemble ToolDefinitions that route to the sandbox daemon.
 *
 * Pi's SDK has two separate option fields:
 *   `tools`       — used ONLY to extract active-tool names (pi still runs its
 *                   own built-in implementations for those names).
 *   `customTools` — real custom ToolDefinitions. Added on top of the built-in
 *                   registry and override by name.
 *
 * So to get pi to actually use our sandbox operations, we pass our tool
 * definitions via `customTools` with the same names as the built-ins
 * (read/bash/edit/write/ls/grep/find). They replace the built-in
 * implementations in the tool registry. The `tools` field only needs the
 * names to mark them active — we return those separately.
 */
import {
  createBashToolDefinition,
  createEditToolDefinition,
  createFindToolDefinition,
  createGrepToolDefinition,
  createLsToolDefinition,
  createReadToolDefinition,
  createWriteToolDefinition,
} from "@mariozechner/pi-coding-agent";

import type { SandboxClient } from "./client.js";
import {
  SANDBOX_CWD_SENTINEL,
  createRemoteBashOps,
  createRemoteEditOps,
  createRemoteFindOps,
  createRemoteGrepOps,
  createRemoteLsOps,
  createRemoteReadOps,
  createRemoteWriteOps,
} from "./remote-ops.js";

export interface SandboxTools {
  /** Tool definitions for pi's `customTools` option. These carry the remote operations. */
  customTools: any[];
  /** Stubs for pi's `tools` option — the name list used to mark them active. */
  activationTools: Array<{ name: string }>;
}

export function buildSandboxTools(client: SandboxClient, allowed: string[]): SandboxTools {
  const cwd = SANDBOX_CWD_SENTINEL;
  const want = new Set(allowed.map((t) => t.trim()).filter(Boolean));
  const customTools: any[] = [];

  if (want.has("read")) customTools.push(createReadToolDefinition(cwd, { operations: createRemoteReadOps(client) }));
  if (want.has("write")) customTools.push(createWriteToolDefinition(cwd, { operations: createRemoteWriteOps(client) }));
  if (want.has("edit")) customTools.push(createEditToolDefinition(cwd, { operations: createRemoteEditOps(client) }));
  if (want.has("ls")) customTools.push(createLsToolDefinition(cwd, { operations: createRemoteLsOps(client) }));
  if (want.has("grep")) customTools.push(createGrepToolDefinition(cwd, { operations: createRemoteGrepOps(client) }));
  if (want.has("find")) customTools.push(createFindToolDefinition(cwd, { operations: createRemoteFindOps(client) }));
  if (want.has("bash")) customTools.push(createBashToolDefinition(cwd, { operations: createRemoteBashOps(client) }));

  return {
    customTools,
    activationTools: customTools.map((t) => ({ name: t.name })),
  };
}

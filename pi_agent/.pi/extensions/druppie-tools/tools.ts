import {
  createBashToolDefinition,
  createEditToolDefinition,
  createFindToolDefinition,
  createGrepToolDefinition,
  createLsToolDefinition,
  createReadToolDefinition,
  createWriteToolDefinition,
} from "@mariozechner/pi-coding-agent";
import type { ToolDefinition } from "@mariozechner/pi-coding-agent";

import type { SandboxClient } from "./sandbox-client.js";
import {
  SANDBOX_CWD_SENTINEL,
  createRemoteBashOps,
  createRemoteEditOps,
  createRemoteFindOps,
  createRemoteGrepOps,
  createRemoteLsOps,
  createRemoteReadOps,
  createRemoteWriteOps,
} from "./sandbox-ops.js";

export interface SandboxTools {
  customTools: ToolDefinition<any, any, any>[];
  activationTools: Array<{ name: string }>;
}

export function buildSandboxTools(client: SandboxClient, allowed: string[]): SandboxTools {
  const cwd = SANDBOX_CWD_SENTINEL;
  const want = new Set(allowed.map((t) => t.trim()).filter(Boolean));
  const customTools: ToolDefinition<any, any, any>[] = [];

  if (want.has("read"))   customTools.push(createReadToolDefinition(cwd, { operations: createRemoteReadOps(client) }));
  if (want.has("write"))  customTools.push(createWriteToolDefinition(cwd, { operations: createRemoteWriteOps(client) }));
  if (want.has("edit"))   customTools.push(createEditToolDefinition(cwd, { operations: createRemoteEditOps(client) }));
  if (want.has("ls"))     customTools.push(createLsToolDefinition(cwd, { operations: createRemoteLsOps(client) }));
  if (want.has("grep"))   customTools.push(createGrepToolDefinition(cwd, { operations: createRemoteGrepOps(client) }));
  if (want.has("find"))   customTools.push(createFindToolDefinition(cwd, { operations: createRemoteFindOps(client) }));
  if (want.has("bash"))   customTools.push(createBashToolDefinition(cwd, { operations: createRemoteBashOps(client) }));

  return {
    customTools,
    activationTools: customTools.map((t) => ({ name: t.name })),
  };
}

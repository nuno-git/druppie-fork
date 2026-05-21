/**
 * Druppie tools extension — routes all tool operations through a sandbox container.
 *
 * Modes:
 * 1. SANDBOX_URL set (child of pi-subagents or pre-started sandbox) → connect to existing
 * 2. No SANDBOX_URL (standalone TUI) → auto-start sandbox + clone source
 */
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

import { SandboxClient } from "./sandbox-client.js";
import { launchSandbox, defaultSandboxLaunchOptions, type LaunchedSandbox } from "./sandbox-lifecycle.js";
import type { RunningSandbox } from "./types.js";
import { cloneSourceIntoSandbox } from "./sandbox-source.js";
import { buildSandboxTools } from "./tools.js";
import { registerGitTools } from "./git-tools.js";
import { registerDoneTool } from "./done.js";
import { registerJournalHooks } from "./journal.js";

export default async function druppieToolsExtension(pi: ExtensionAPI): Promise<void> {
  let launched: LaunchedSandbox | null = null;
  let client: SandboxClient;

  const existingUrl = process.env.SANDBOX_URL;
  if (existingUrl) {
    const parsed = new URL(existingUrl);
    client = new SandboxClient({
      host: parsed.hostname,
      port: Number(parsed.port) || 8000,
      authToken: process.env.SANDBOX_AUTH_TOKEN ?? "",
    });
  } else {
    const opts = defaultSandboxLaunchOptions();
    launched = await launchSandbox(opts);
    client = launched.client;

    process.env.SANDBOX_URL = `http://${launched.host}:${launched.hostPort}`;
    process.env.SANDBOX_AUTH_TOKEN = launched.authToken;

    const repoUrl = process.env.SOURCE_REPO_URL;
    const branch = process.env.SOURCE_REPO_BRANCH ?? "main";
    const token = process.env.SOURCE_REPO_TOKEN;

    if (repoUrl && token) {
      await cloneSourceIntoSandbox(
        client,
        { host: launched.host, port: launched.hostPort, authToken: launched.authToken },
        { remoteUrl: repoUrl, branch, token },
      );
    }
  }

  const toolNames = (process.env.PI_AGENT_TOOLS ?? "read,write,edit,bash,ls,grep,find").split(",");
  const { customTools, activationTools } = buildSandboxTools(client, toolNames);

  for (const tool of customTools) {
    pi.registerTool(tool);
  }

  const activeNames = pi.getActiveTools();
  pi.setActiveTools([...new Set([...activeNames, ...activationTools.map((t) => t.name)])]);

  registerDoneTool(pi);
  if (launched) {
    registerGitTools(pi, client, launched);
  } else {
    const ep = client.getEndpoint();
    const runningSandbox: RunningSandbox = {
      containerName: "pre-launched",
      bundleHostDir: process.env.PI_AGENT_BUNDLE_HOST_DIR ?? "/app/pi_agent_bundles",
      authToken: ep.authToken,
      host: ep.host ?? "localhost",
      hostPort: ep.port ?? 8000,
      stop: () => {},
    };
    registerGitTools(pi, client, runningSandbox);
  }
  registerJournalHooks(pi);

  pi.on("session_shutdown", () => {
    if (launched) {
      launched.stop();
      launched = null;
    }
  });
}

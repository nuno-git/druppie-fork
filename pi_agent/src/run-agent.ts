/**
 * run-agent — run a SINGLE agent with sandbox, enforced done-tool, and JSON output.
 *
 * This is the foundation for Python-based flow orchestration. The Python
 * backend calls `node pi_agent/dist/cli.js run-agent ...` and parses the
 * final JSON line from stdout.
 *
 * All progress/logging goes to stderr so the JSON on stdout is clean.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { mkdtempSync } from "node:fs";
import type { Api, Model } from "@mariozechner/pi-ai";
import { AuthStorage, ModelRegistry } from "@mariozechner/pi-coding-agent";

import { Journal } from "./journal.js";
import {
  defaultSandboxLaunchOptions,
  launchSandbox,
  type RunningSandbox,
} from "./sandbox/lifecycle.js";
import { SandboxClient } from "./sandbox/client.js";
import { SandboxGitOps } from "./sandbox/sandbox-git.js";
import { cloneSourceIntoSandbox } from "./sandbox/source-clone.js";
import { selectGitProvider } from "./git/provider.js";
import {
  discoverAgents,
  runSubagent,
  type AgentDefinition,
  type RunSubagentOptions,
} from "./agents/runner.js";
import { createSpawnSubagentsTool } from "./flows/tools/spawn-subagents-tool.js";

// ── Public Interface ──────────────────────────────────────────

export interface SingleAgentParams {
  agent: string;
  prompt: string;
  workDir: string;
  projectRoot?: string;
  model?: string;
  apiKey?: string;
  glmApiKey?: string;
  maxTurns?: number;
  // Sandbox — either launch new or connect to existing
  sandboxLaunch?: boolean;
  sandboxImage?: string;
  sandboxHost?: string;
  sandboxPort?: number;
  sandboxAuthToken?: string;
  // Source repo to clone
  sourceRepoUrl?: string;
  sourceBranch?: string;
  pushToken?: string;
  // Journal ingest (for event streaming back to backend)
  ingestUrl?: string;
  ingestToken?: string;
  ingestRunId?: string;
}

export interface SingleAgentResult {
  output: string;
  summary: string;
  variables: Record<string, unknown>;
  success: boolean;
  toolCallsUsed: string[];
}

// ── Main Function ─────────────────────────────────────────────

export async function runSingleAgent(params: SingleAgentParams): Promise<SingleAgentResult> {
  // Set up journal ingest env vars if provided
  if (params.ingestUrl) process.env.PI_AGENT_INGEST_URL = params.ingestUrl;
  if (params.ingestToken) process.env.PI_AGENT_INGEST_TOKEN = params.ingestToken;

  const cwd = params.workDir;
  const projectRoot = params.projectRoot ?? cwd;
  let sandbox: RunningSandbox | undefined;
  let sandboxClient: SandboxClient;
  let sandboxLaunchedHere = false;

  try {
    // ── 1. Sandbox ──────────────────────────────────────────────
    if (params.sandboxLaunch) {
      const launchOpts = {
        ...defaultSandboxLaunchOptions(),
        ...(params.sandboxImage ? { image: params.sandboxImage } : {}),
      };
      sandbox = await launchSandbox(launchOpts);
      sandboxClient = sandbox.client;
      sandboxLaunchedHere = true;
    } else if (params.sandboxHost) {
      sandboxClient = new SandboxClient({
        host: params.sandboxHost,
        port: params.sandboxPort ?? 8000,
        authToken: params.sandboxAuthToken ?? "",
      });
    } else {
      // No sandbox — create a dummy client that won't be used.
      // The agent will run with local tools instead.
      sandboxClient = undefined as unknown as SandboxClient;
    }

    // ── 2. Source clone ─────────────────────────────────────────
    if (params.sourceRepoUrl && sandbox) {
      const gitProvider = selectGitProvider();
      const token = await gitProvider.resolveToken() ?? params.pushToken;
      if (!token) {
        throw new Error("sourceRepoUrl set but no credentials available");
      }
      const sourceBranch = params.sourceBranch ?? "main";
      const git = new SandboxGitOps(sandboxClient);
      await cloneSourceIntoSandbox(
        sandboxClient,
        { host: sandbox.host, port: sandbox.hostPort, authToken: sandbox.authToken },
        { remoteUrl: params.sourceRepoUrl, branch: sourceBranch, token },
      );
      await git.init();
    } else if (params.sourceRepoUrl && !sandbox) {
      // Source clone without sandbox — not supported
      throw new Error("sourceRepoUrl requires a sandbox (--sandbox-launch or --sandbox-host)");
    }

    // ── 3. Discover agents ──────────────────────────────────────
    const extraAgentDirs: string[] = [];
    if (projectRoot) extraAgentDirs.push(join(projectRoot, ".pi", "agents"));
    const agents = discoverAgents(cwd, extraAgentDirs);
    const agentDef = agents.find((a) => a.name === params.agent);
    if (!agentDef) {
      throw new Error(
        `Agent "${params.agent}" not found. Available: ${agents.map((a) => a.name).join(", ") || "(none)"}`,
      );
    }

    // ── 4. LLM setup (same pattern as explore.ts) ──────────────
    const authStorage = AuthStorage.create();
    if (params.apiKey) authStorage.setRuntimeApiKey("anthropic", params.apiKey);
    if (params.glmApiKey) authStorage.setRuntimeApiKey("zai", params.glmApiKey);

    const modelRegistry = ModelRegistry.create(authStorage);
    const modelSpec = params.model ?? "zai/glm-5.1";
    let defaultModel: Model<Api> | undefined;
    if (modelSpec.includes("/")) {
      const [prov, id] = modelSpec.split("/", 2);
      defaultModel = modelRegistry.find(prov, id);
    } else {
      defaultModel = modelRegistry.getAll().find((m) => m.id === modelSpec);
    }
    if (!defaultModel) throw new Error(`Default model not found: ${modelSpec}`);

    // ── 5. Journal ─────────────────────────────────────────────
    const runTimestamp = new Date().toISOString().replace(/[:.]/g, "-");
    const runsRoot = projectRoot ? join(projectRoot, "sessions", "runs") : join(cwd, "runs");
    const journalDir = join(runsRoot, runTimestamp);
    const taskSpec = { description: params.prompt, language: "unknown" };
    const journal = new Journal(journalDir, taskSpec);

    // ── 6. Build tool injections ────────────────────────────────
    const extraCustomTools: any[] = [];

    const parentRef: { current?: string } = {};

    // Auto-inject spawn tool if agent has spawn_subagents enabled
    const agentMap = new Map(agents.map((a) => [a.name, a]));
    if (agentDef.spawn_subagents && agentDef.allowed_subagents && agentDef.allowed_subagents.length > 0) {
      const baseOpts: RunSubagentOptions = {
        cwd,
        authStorage,
        modelRegistry,
        defaultModel,
        maxTurns: params.maxTurns ?? 40,
        onOutput: (delta) => process.stderr.write(delta),
        sandboxClient,
        journal,
      };
      const spawnTool = createSpawnSubagentsTool({
        agentMap,
        allowedAgents: agentDef.allowed_subagents,
        baseOpts,
        parentRef,
      });
      extraCustomTools.push(spawnTool);
    }

    // ── 7. Run the agent ───────────────────────────────────────
    parentRef.current = `${agentDef.name}-1`;

    const sessionsDir = process.env.PI_AGENT_INGEST_URL
      ? `/tmp/pi-agent-transcripts-${process.pid}`
      : journalDir;

    const subResult = await runSubagent(agentDef, params.prompt, {
      cwd,
      authStorage,
      modelRegistry,
      defaultModel,
      maxTurns: params.maxTurns ?? 40,
      onOutput: (delta) => process.stderr.write(delta),
      sessionsDir,
      sandboxClient,
      journal,
      extraCustomTools,
    });

    const agentNarrative = subResult.doneMessage || subResult.output || "";
    if (agentNarrative) {
      journal.recordNarrative(`${agentDef.name}`, 1, agentNarrative);
    }

    // ── 8. Build final result ───────────────────────────────────
    const finalResult: SingleAgentResult = {
      output: subResult.output,
      summary: subResult.doneMessage || subResult.output.slice(0, 500),
      variables: subResult.doneVariables,
      success: subResult.success && subResult.doneCalled,
      toolCallsUsed: [...subResult.toolCallsUsed],
    };

    // ── 9. Teardown ────────────────────────────────────────────
    await journal.close(finalResult.success);
    if (sandboxLaunchedHere && sandbox) {
      sandbox.stop();
    }

    return finalResult;
  } catch (err) {
    const errorMsg = err instanceof Error ? err.message : String(err);
    process.stderr.write(`[run-agent] Error: ${errorMsg}\n`);

    // Teardown sandbox if we launched it
    if (sandboxLaunchedHere && sandbox) {
      try { sandbox.stop(); } catch { /* ignore */ }
    }

    // Always return valid JSON even on crash
    return {
      output: "",
      summary: "",
      variables: {},
      success: false,
      toolCallsUsed: [],
    };
  }
}

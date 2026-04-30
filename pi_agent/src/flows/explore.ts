/**
 * Explore flow — LLM-driven investigation inside a sandboxed clone.
 *
 * Unlike the TDD flow (hardcoded analyst → plan → execute → verify pipeline),
 * the explore flow is a single "router" agent session:
 *
 *   router (inside sandbox)
 *     tools: bash, read, grep, find           ← direct reading
 *            spawn_parallel_explorers          ← fan-out for independent sub-questions
 *            done                              ← finish with the answer
 *
 * The router decides when to look directly, when to fan out, and when it has
 * enough to answer. No commits, no push, no PR — purely read-only.
 */
import { join } from "node:path";
import type { Api, Model } from "@mariozechner/pi-ai";
import { AuthStorage, ModelRegistry } from "@mariozechner/pi-coding-agent";

import { selectGitProvider } from "../git/provider.js";
import { Journal } from "../journal.js";
import { startSimServer, type SimServer } from "../providers/sim.js";
import { defaultSandboxLaunchOptions, launchSandbox, type RunningSandbox } from "../sandbox/lifecycle.js";
import { SandboxGitOps } from "../sandbox/sandbox-git.js";
import { cloneSourceIntoSandbox } from "../sandbox/source-clone.js";
import {
  discoverAgents,
  runSubagent,
  type AgentDefinition,
  type RunSubagentOptions,
} from "../agents/runner.js";
import type { AgentConfig, RunResult, TaskSpec } from "../types.js";

import { createSpawnParallelExplorersTool } from "./spawn-tool.js";

export async function runExploreFlow(task: TaskSpec, config: AgentConfig): Promise<RunResult> {
  const cwd = config.workDir;
  const errors: string[] = [];

  // Journal — same structure as the TDD flow so the druppie ingest endpoint
  // and the frontend PiCodingRunCard don't need special-casing.
  const runTimestamp = new Date().toISOString().replace(/[:.]/g, "-");
  const runsRoot = config.projectRoot ? join(config.projectRoot, "sessions", "runs") : join(cwd, "runs");
  const journalDir = join(runsRoot, runTimestamp);
  const journal = new Journal(journalDir, task);

  const gitProvider = selectGitProvider();
  journal.write("git_provider_selected", { kind: gitProvider.kind });
  journal.write("flow_selected", { flow: "explore" });

  // Sandbox lifecycle — same as TDD (read-only will be enforced at the
  // toolset level, not by making the sandbox itself read-only, because the
  // explorer sometimes needs to run `npm install` or similar to answer
  // "what happens when I run X" questions).
  const launchOpts = {
    ...defaultSandboxLaunchOptions(),
    ...(config.sandbox?.image ? { image: config.sandbox.image } : {}),
    ...(config.sandbox?.memoryLimit ? { memoryLimit: config.sandbox.memoryLimit } : {}),
    ...(config.sandbox?.cpuLimit ? { cpuLimit: config.sandbox.cpuLimit } : {}),
    ...(config.sandbox?.pidsLimit ? { pidsLimit: config.sandbox.pidsLimit } : {}),
    ...(config.sandbox?.allowNetwork !== undefined ? { allowNetwork: config.sandbox.allowNetwork } : {}),
    ...(config.sandbox?.timeoutSec ? { timeoutSec: config.sandbox.timeoutSec } : {}),
  };
  journal.sandboxStart("(pending)", launchOpts.runtime);
  const sandbox: RunningSandbox = await launchSandbox(launchOpts);
  journal.sandboxReady();
  journal.write("sandbox_ready", { containerName: sandbox.containerName, hostPort: sandbox.hostPort });

  const git = new SandboxGitOps(sandbox.client);
  let simServer: SimServer | undefined;

  try {
    // Clone the repo into the sandbox if a sourceRepoUrl is set.
    if (task.sourceRepoUrl) {
      const token = await gitProvider.resolveToken() ?? config.sandbox?.pushToken;
      if (!token) {
        throw new Error("task.sourceRepoUrl set but no credentials (resolveToken returned undefined)");
      }
      const sourceBranch = task.sourceBranch ?? "main";
      journal.sourceClone(task.sourceRepoUrl, sourceBranch);
      await cloneSourceIntoSandbox(
        sandbox.client,
        { host: sandbox.host, port: sandbox.hostPort, authToken: sandbox.authToken },
        { remoteUrl: task.sourceRepoUrl, branch: sourceBranch, token },
      );
      await git.init();
    }

    // Discover the explorer + router agent prompts (same search paths as tdd).
    const extraAgentDirs: string[] = [];
    if (config.projectRoot) extraAgentDirs.push(join(config.projectRoot, ".pi", "agents"));
    const agents = discoverAgents(cwd, extraAgentDirs);
    const findAgent = (name: string): AgentDefinition => {
      const a = agents.find((x) => x.name === name);
      if (!a) throw new Error(`Agent "${name}" not found in .pi/agents/. Available: ${agents.map((x) => x.name).join(", ")}`);
      return a;
    };
    const router = findAgent("router");
    const explorer = findAgent("explorer");

    // LLM setup — AuthStorage.create() / ModelRegistry.create() pattern.
    const authStorage = AuthStorage.create();
    if (config.apiKey) authStorage.setRuntimeApiKey("anthropic", config.apiKey);
    const modelRegistry = ModelRegistry.create(authStorage);
    if (config.glmApiKey) authStorage.setRuntimeApiKey("zai", config.glmApiKey);

    const modelSpec = config.model ?? "zai/glm-5.1";
    let defaultModel: Model<Api> | undefined;
    if (modelSpec.includes("/")) {
      const [prov, id] = modelSpec.split("/", 2);
      defaultModel = modelRegistry.find(prov, id);
    } else {
      defaultModel = modelRegistry.getAll().find((m) => m.id === modelSpec);
    }
    if (!defaultModel) throw new Error(`Default model not found: ${modelSpec}`);

    // Per-subagent transcripts dir — ephemeral under druppie, local-file under standalone.
    const sessionsDir = process.env.PI_AGENT_INGEST_URL
      ? `/tmp/pi-agent-transcripts-${process.pid}`
      : journalDir;

    const baseOpts: RunSubagentOptions = {
      cwd,
      authStorage,
      modelRegistry,
      defaultModel,
      maxTurns: config.maxTurnsPerAgent ?? 40,
      onOutput: (delta) => process.stdout.write(delta),
      sessionsDir,
      sandboxClient: sandbox.client,
      journal,
    };

    // parentRef lets the spawn tool stamp each explorer's `parentAgentId`
    // at execute-time so the UI can render the hierarchy correctly.
    const parentRef: { current?: string } = {};
    const spawnTool = createSpawnParallelExplorersTool({
      explorer,
      baseOpts,
      parentRef,
      onRoundComplete: (round, results) => {
        for (const r of results) {
          journal.recordNarrative(`explorer/${r.id}`, round, r.output);
        }
      },
    });

    // The router is a subagent. It signals "I'm finished" by emitting a
    // final assistant message with no tool calls — pi's session stops
    // naturally. We take `routerResult.output` as the answer. There is
    // no concatenate-explorer-findings fallback: that's garbage data.
    // If the router doesn't produce text, we RETRY with a direct nudge,
    // up to MAX_ROUTER_ATTEMPTS. If all attempts are empty the run fails.
    const routerBasePrompt = [
      `## Question`,
      task.description,
      ``,
      `Answer this by reading the repo (cloned at /workspace) directly with bash/read/grep/find,`,
      `and/or by calling spawn_parallel_explorers when you need several independent lookups at once.`,
      ``,
      `When you have a solid answer, write it as your final assistant message. That final message`,
      `IS your answer — no special tool is needed. After the synthesis, stop calling tools and`,
      `stop writing; the loop ends when you end your turn without any tool calls.`,
    ].join("\n");

    const MAX_ROUTER_ATTEMPTS = 3;
    let finalAnswer = "";
    let lastRouterError: string | undefined;

    for (let attempt = 1; attempt <= MAX_ROUTER_ATTEMPTS; attempt++) {
      const isRetry = attempt > 1;
      // On retry, include the prior explorer findings in the prompt so the
      // model has context — we can't reuse the previous session, each
      // attempt spawns a fresh one. Cap to 12 entries to keep it bounded.
      const findings = journal.getNarratives()
        .filter((n) => n.agent.startsWith("explorer/"))
        .slice(-12)
        .map((n) => `### ${n.agent} (iter ${n.iteration})\n${n.text}`)
        .join("\n\n");

      const promptForThisAttempt = !isRetry
        ? routerBasePrompt
        : [
            `## Retry ${attempt}/${MAX_ROUTER_ATTEMPTS} — your previous attempt ended without a final answer.`,
            ``,
            `You did the investigation but did NOT emit a final assistant message. The only thing`,
            `you need to do this turn is write your synthesised answer as a plain assistant message.`,
            `Do not call any tools. Just write the answer and stop.`,
            ``,
            `## Original question`,
            task.description,
            ``,
            `## Findings from the earlier explorers`,
            findings || "(no explorer findings recorded yet — answer from general knowledge and what you already read)",
          ].join("\n");

      journal.phaseStart("EXPLORE", attempt);
      parentRef.current = `router-${attempt}`;
      const routerResult = await runSubagent(router, promptForThisAttempt, {
        ...baseOpts,
        extraCustomTools: [spawnTool],
        maxTurns: 60,
        meta: { role: "orchestrator", attempt },
      } as any);
      journal.recordNarrative(`router/attempt-${attempt}`, attempt, routerResult.output || routerResult.doneMessage || "");
      journal.phaseEnd();

      if (!routerResult.success) {
        lastRouterError = routerResult.error ?? "unknown";
        break;  // hard error (not just empty output) — stop retrying.
      }

      const text = (routerResult.output ?? "").trim() || routerResult.doneMessage?.trim() || "";
      if (text) {
        finalAnswer = text;
        if (isRetry) {
          journal.write("router_retry_recovered", { attempts: attempt });
        }
        break;
      }

      journal.write("router_retry", {
        attempt,
        reason: "empty final message",
        willRetry: attempt < MAX_ROUTER_ATTEMPTS,
      });
    }

    if (!finalAnswer) {
      errors.push(
        lastRouterError
          ? `Router failed: ${lastRouterError}`
          : `Router produced no final message after ${MAX_ROUTER_ATTEMPTS} attempts.`,
      );
    }

    const success = !!finalAnswer && errors.length === 0;
    for (const e of errors) journal.error(e);
    sandbox.stop();
    journal.sandboxStop();
    if (simServer) await simServer.stop();
    const { summary } = await journal.close(success);

    // The final answer also lands in summary.narratives[] as an
    // "answer" entry so Python (which reads summary.narratives) can
    // surface it cleanly alongside the exploration reports.
    if (finalAnswer) {
      journal.recordNarrative("answer", 0, finalAnswer);
    }

    return {
      success,
      branch: "",
      commits: [],
      testsPassed: false,
      buildPassed: false,
      summary: finalAnswer,
      errors,
      stepResults: [],
      iterations: 1,
    };
  } catch (err) {
    errors.push(`Explore flow crashed: ${err instanceof Error ? err.message : String(err)}`);
    for (const e of errors) journal.error(e);
    sandbox.stop();
    journal.sandboxStop();
    if (simServer) await simServer.stop();
    await journal.close(false);
    return {
      success: false,
      branch: "",
      commits: [],
      testsPassed: false,
      buildPassed: false,
      summary: "",
      errors,
      stepResults: [],
      iterations: 0,
    };
  }
}

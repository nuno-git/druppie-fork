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
import { Type } from "@sinclair/typebox";
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

// `done(answer)` tool so the router can return a structured final answer.
const DoneParams = Type.Object({
  answer: Type.String({ description: "Final synthesized answer to the original question." }),
});

function createDoneTool(onDone: (answer: string) => void): any {
  return {
    name: "done",
    label: "Done",
    description: "Finish the exploration with a synthesized answer to the original question. Call this once you have enough context.",
    promptSnippet: "done: return the final answer text. Exactly once, at the end.",
    parameters: DoneParams,
    async execute(_toolCallId: string, params: { answer: string }) {
      onDone(params.answer);
      return { output: "recorded", details: { length: params.answer.length } };
    },
  };
}

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
        { host: "127.0.0.1", port: sandbox.hostPort, authToken: sandbox.authToken },
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

    // LLM setup — mirror tdd.ts exactly (private constructors, use .create()).
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

    // Assemble the router's custom tools. `done` captures the final answer
    // by mutating this outer variable; cleaner than trying to thread it
    // through pi's event protocol.
    let finalAnswer: string | undefined;
    const spawnTool = createSpawnParallelExplorersTool({
      explorer,
      baseOpts,
      onRoundComplete: (round, results) => {
        for (const r of results) {
          journal.recordNarrative(`explorer/${r.id}`, round, r.output);
        }
      },
    });
    const doneTool = createDoneTool((answer) => {
      finalAnswer = answer;
    });

    // Pass the router the spawn+done tools on top of its read tools.
    // We extend the runSubagent options with customTools, threaded through
    // via a cast so we don't have to modify RunSubagentOptions.
    journal.phaseStart("EXPLORE", 1);
    const routerPrompt = [
      `## Question`,
      task.description,
      ``,
      `Answer this by reading the repo (cloned at /workspace) directly with bash/read/grep/find,`,
      `and/or by calling spawn_parallel_explorers when you need several independent lookups at once.`,
      `When you have a solid answer, call done(answer: "<your synthesis>"). Do not output the final`,
      `answer as plain text — it must come through the done tool.`,
    ].join("\n");

    const routerResult = await runSubagent(router, routerPrompt, {
      ...baseOpts,
      // HACK: pi-coding-agent supports extra custom tools via a field that
      // isn't exposed on RunSubagentOptions today. We cast to allow the
      // injection; runner.ts forwards anything extra into the session.
      extraCustomTools: [spawnTool, doneTool],
    } as any);

    journal.recordNarrative("router", 1, routerResult.output);
    journal.phaseEnd();

    if (!routerResult.success) {
      errors.push(`Router failed: ${routerResult.error ?? "unknown"}`);
    } else if (finalAnswer === undefined) {
      errors.push("Router finished without calling done() — no final answer produced");
    }

    const success = errors.length === 0 && finalAnswer !== undefined;
    for (const e of errors) journal.error(e);
    sandbox.stop();
    journal.sandboxStop();
    if (simServer) await simServer.stop();
    const { summary } = await journal.close(success);

    // The final answer also lands in summary.narratives[] as an
    // "answer" entry so Python (which reads summary.narratives) can
    // surface it cleanly alongside the exploration reports.
    if (finalAnswer !== undefined) {
      journal.recordNarrative("answer", 0, finalAnswer);
    }

    return {
      success,
      branch: "",
      commits: [],
      testsPassed: false,
      buildPassed: false,
      summary: finalAnswer ?? "",
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

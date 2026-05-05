/**
 * run-agent — thin CLI runner that delegates to the druppie-tools extension
 * for sandbox lifecycle and tool creation, and pi-subagents for agent execution.
 *
 * All progress/logging goes to stderr so the JSON on stdout is clean.
 */
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import type { Model, Api } from "@mariozechner/pi-ai";
import {
  AuthStorage,
  ModelRegistry,
  createAgentSession,
  DefaultResourceLoader,
  SessionManager,
  SettingsManager,
} from "@mariozechner/pi-coding-agent";
import { Type } from "@sinclair/typebox";

import { Journal } from "./journal.js";
import type { TaskSpec } from "./types.js";

import { SandboxClient } from "../.pi/extensions/druppie-tools/sandbox-client.js";
import { launchSandbox, defaultSandboxLaunchOptions, type LaunchedSandbox } from "../.pi/extensions/druppie-tools/sandbox-lifecycle.js";
import { cloneSourceIntoSandbox } from "../.pi/extensions/druppie-tools/sandbox-source.js";
import { SandboxGitOps } from "../.pi/extensions/druppie-tools/sandbox-git.js";
import { pushBundleIsolated } from "../.pi/extensions/druppie-tools/sandbox-push.js";
import { buildSandboxTools } from "../.pi/extensions/druppie-tools/tools.js";
import { selectGitProvider, parseRemote } from "../.pi/extensions/druppie-tools/git-providers.js";

export interface SingleAgentParams {
  agent: string;
  prompt: string;
  workDir: string;
  projectRoot?: string;
  model?: string;
  apiKey?: string;
  glmApiKey?: string;
  maxTurns?: number;
  sandboxLaunch?: boolean;
  sandboxImage?: string;
  sandboxHost?: string;
  sandboxPort?: number;
  sandboxAuthToken?: string;
  sourceRepoUrl?: string;
  sourceBranch?: string;
  pushToken?: string;
  ingestUrl?: string;
  ingestToken?: string;
  ingestRunId?: string;
  sandboxClient?: SandboxClient;
  /** When this agent is a subagent of another pi_agent, the parent's
   *  agent id (e.g. "planner-1"). Passed through to journal events so
   *  the UI can nest children under the parent tool_call that spawned
   *  them instead of rendering everything as top-level agents. */
  parentAgentId?: string;
  /** Load agent prompt from a different agent name than the one used for
   *  journal/display. When set, prompt loading uses this name (e.g. "builder")
   *  while journal events and the UI use `agent` (e.g. "builder-1"). */
  loadAgent?: string;
  /** The tool_call id on the parent agent that spawned this subagent.
   *  Matched against { type: "tool_call", callId } in the journal to
   *  group parallel subagents under the correct parent row. */
  parentToolCallId?: string;
}

export interface SingleAgentResult {
  output: string;
  summary: string;
  variables: Record<string, unknown>;
  success: boolean;
  toolCallsUsed: string[];
}

export async function runSingleAgent(params: SingleAgentParams): Promise<SingleAgentResult> {
  if (params.ingestUrl) process.env.PI_AGENT_INGEST_URL = params.ingestUrl;
  if (params.ingestToken) process.env.PI_AGENT_INGEST_TOKEN = params.ingestToken;

  const cwd = params.workDir;
  const projectRoot = params.projectRoot ?? cwd;
  let sandbox: LaunchedSandbox | undefined;
  let sandboxClient: SandboxClient | undefined;
  let sandboxLaunchedHere = false;

  try {
    if (params.sandboxClient) {
      sandboxClient = params.sandboxClient;
      const ep = sandboxClient.getEndpoint();
      process.env.SANDBOX_URL = `http://${ep.host}:${ep.port ?? 8000}`;
      process.env.SANDBOX_AUTH_TOKEN = ep.authToken ?? "";
      if (params.parentAgentId) {
        process.stderr.write(`[run-agent] subagent ${params.agent} using parent sandbox at ${process.env.SANDBOX_URL}\n`);
      }
    } else if (params.sandboxLaunch) {
      const launchOpts = {
        ...defaultSandboxLaunchOptions(),
        ...(params.sandboxImage ? { image: params.sandboxImage } : {}),
      };
      sandbox = await launchSandbox(launchOpts);
      sandboxClient = sandbox.client;
      sandboxLaunchedHere = true;
      process.env.SANDBOX_URL = `http://${sandbox.host}:${sandbox.hostPort}`;
      process.env.SANDBOX_AUTH_TOKEN = sandbox.authToken;
    } else if (params.sandboxHost) {
      process.env.SANDBOX_URL = `http://${params.sandboxHost}:${params.sandboxPort ?? 8000}`;
      process.env.SANDBOX_AUTH_TOKEN = params.sandboxAuthToken ?? "";
    }

    if (params.sourceRepoUrl && sandbox) {
      await cloneSourceIntoSandbox(sandboxClient!, { host: sandbox.host, port: sandbox.hostPort, authToken: sandbox.authToken }, {
        remoteUrl: params.sourceRepoUrl!,
        branch: params.sourceBranch ?? "main",
        token: params.pushToken ?? "",
      });
    } else if (params.sourceRepoUrl && !sandbox && !sandboxClient) {
      // sandboxClient from parent = we're inside an already-set-up sandbox;
      // the source was already cloned by the parent agent, skip the clone.
      throw new Error("sourceRepoUrl requires a sandbox (--sandbox-launch or --sandbox-host)");
    }

    // Create a feature branch before the agent session so all work lands on it.
    {
      const gitBranchSgit = new SandboxGitOps(sandboxClient!);
      const currentBranch = await gitBranchSgit.getCurrentBranch().catch(() => "main");
      const defaultBranch = params.sourceBranch || "main";
      if (currentBranch === defaultBranch) {
        const timestamp = Date.now().toString(36);
        const featureBranch = "pi-agent-" + timestamp;
        await gitBranchSgit.createBranch(featureBranch);
        process.stderr.write("[run-agent] created feature branch " + featureBranch + "\n");
      }
    }

    const authStorage = AuthStorage.create();
    if (params.apiKey) authStorage.setRuntimeApiKey("anthropic", params.apiKey);
    if (params.glmApiKey) authStorage.setRuntimeApiKey("zai", params.glmApiKey);

    const modelRegistry = ModelRegistry.create(authStorage);
    const defaultModel = resolveModel(modelRegistry, params.model ?? "zai/glm-5.1");

    const runTimestamp = new Date().toISOString().replace(/[:.]/g, "-");
    const runsRoot = projectRoot ? join(projectRoot, "sessions", "runs") : join(cwd, "runs");
    const journalDir = join(runsRoot, runTimestamp);
    const journal = new Journal(journalDir, { description: params.prompt, language: "unknown" }, params.ingestUrl, params.ingestToken);

    const toolNames = ["read", "write", "edit", "bash", "grep", "find", "ls"];
    const { customTools: sandboxCustomTools, activationTools } = sandboxClient
      ? buildSandboxTools(sandboxClient, toolNames)
      : { customTools: [], activationTools: [] };

    const doneTool = {
      name: "done",
      label: "Mark Work as Complete",
      description: "Mark your work as complete. YOU MUST USE THIS TOOL TO FINISH.",
      promptSnippet: "done: mark your work as complete and set variables",
      parameters: Type.Object({
        variables: Type.Record(Type.String(), Type.Unknown()),
        message: Type.String({ description: "Completion message." }),
      }),
      // terminate:true prevents tool_execution_end from firing,
      // which means doneCalled never becomes true — success is instead
      // determined by doneCalled being true after session.prompt() returns.
      async execute(_toolCallId: string, params: { variables: Record<string, unknown>; message: string }) {
        return {
          content: [{ type: "text" as const, text: JSON.stringify({ success: true, message: params.message, variables: params.variables }) }],
        };
      },
    };

    const agentModel = params.model;
    const agentApiKey = params.apiKey;
    const agentGlmApiKey = params.glmApiKey;
    const agentProjectRoot = projectRoot;
    const agentSourceRepoUrl = params.sourceRepoUrl;
    const agentSourceBranch = params.sourceBranch;
    const agentPushToken = params.pushToken;
    const agentIngestUrl = params.ingestUrl;
    const agentIngestToken = params.ingestToken;
    const agentIngestRunId = params.ingestRunId;

    const subagentTool = {
      name: "subagents",
      label: "Spawn Sub Agents",
      description: `Spawn one or more sub-agents to perform work in the sandbox (parallel execution).
Each sub-agent runs the same tools in the same sandbox as the current agent.
Parameters:
- tasks: array of {agent: string, task: string} — spawn multiple agents (run in parallel)
- agent: string — single agent name (use instead of tasks for one agent)
- task: string — single task prompt (use with agent for one agent)`,
      promptSnippet: "subagents: spawn sub-agents to delegate work",
      parameters: Type.Object({
        tasks: Type.Optional(Type.Array(Type.Object({
          agent: Type.String({ description: "Agent name (e.g. builder, pusher)" }),
          task: Type.String({ description: "Task prompt for this agent" }),
        }), { description: "Array of agent tasks to spawn (parallel execution)" })),
        agent: Type.Optional(Type.String({ description: "Single agent name (use with task)" })),
        task: Type.Optional(Type.String({ description: "Single task prompt (use with agent)" })),
      }),
      async execute(toolCallId: string, toolParams: { tasks?: { agent: string; task: string }[]; agent?: string; task?: string }) {
        const taskList = toolParams.tasks ?? (toolParams.agent && toolParams.task ? [{ agent: toolParams.agent, task: toolParams.task }] : []);
        if (taskList.length === 0) {
          return { content: [{ type: "text" as const, text: "Error: no tasks provided. Provide tasks=[...] or agent+task." }] };
        }
        // Assign unique names by appending index for duplicate agent names
        const nameCounts = new Map();
        const namedTasks = taskList.map((t) => {
          const key = t.agent;
          const count = (nameCounts.get(key) ?? 0) + 1;
          nameCounts.set(key, count);
          return { ...t, agentName: taskList.length === 1 ? key : `${key}-${count}` };
        });
        // Run all subagents in parallel, passing parentAgentId + parentToolCallId
        // so their journal events carry the linkage for the UI to nest them under
        // this tool call's row instead of rendering them as top-level agents.
        // Capture the requested agent names before spawning so we can report
        // on ALL of them even if some never started (e.g. crashed during init).
        const requestedNames = namedTasks.map((t) => t.agentName);
        const spawned: string[] = [];

        const futures = namedTasks.map(async (t) => {
          process.stderr.write(`[subagent] spawning ${t.agentName}: ${t.task.slice(0, 120)}...\n`);
          spawned.push(t.agentName);
          const startMs = Date.now();
          try {
            const agentResult = await runSingleAgent({
              agent: t.agentName,
              loadAgent: t.agent,
              prompt: t.task,
              workDir: agentProjectRoot,
              projectRoot: agentProjectRoot,
              model: agentModel,
              apiKey: agentApiKey,
              glmApiKey: agentGlmApiKey,
              maxTurns: 30,
              sandboxClient: sandboxClient ?? undefined,
              sandboxHost: params.sandboxHost,
              sandboxPort: params.sandboxPort ?? 8000,
              sandboxAuthToken: params.sandboxAuthToken ?? "",
              sourceRepoUrl: agentSourceRepoUrl,
              sourceBranch: agentSourceBranch,
              pushToken: agentPushToken,
              ingestUrl: agentIngestUrl,
              ingestToken: agentIngestToken,
              ingestRunId: agentIngestRunId,
              parentAgentId: handle.id,
              parentToolCallId: toolCallId,
            });
            const elapsedMs = Date.now() - startMs;
            if (agentResult.success) {
              return `[${t.agentName}] SUCCESS (${elapsedMs}ms): ${agentResult.summary}`;
            } else if (agentResult.output) {
              return `[${t.agentName}] FAILED (${elapsedMs}ms): ${agentResult.output.slice(0, 500)}`;
            } else {
              return `[${t.agentName}] FAILED (${elapsedMs}ms): ${agentResult.summary || "no output, no exception"}`;
            }
          } catch (err: any) {
            const elapsedMs = Date.now() - startMs;
            const errMsg = err instanceof Error ? err.message : String(err);
            const errStack = err instanceof Error && err.stack ? err.stack.slice(0, 500) : errMsg;
            process.stderr.write(`[subagent] ${t.agentName} error (${elapsedMs}ms): ${errMsg}\n${errStack}\n`);
            return `[${t.agentName}] ERROR (${elapsedMs}ms): ${errMsg}`;
          }
        });
        const results = await Promise.all(futures);
        // Report how many were requested vs how many actually ran so callers
        // (frontend, logs) can detect partial failures.
        const summary =
          `[subagents] ${results.length}/${requestedNames.length} subagents completed:` +
          ` requested=${requestedNames.join(",")}` +
          (spawned.length !== requestedNames.length ? ` launched=${spawned.length}` : "") +
          `\n` +
          results.join("\n");
        return { content: [{ type: "text" as const, text: summary }] };
      },
    };

    const loadName = params.loadAgent ?? params.agent;
    const { frontmatter, prompt: agentPrompt } = loadAgentPrompt(loadName, projectRoot, cwd);

    const customTools = [...sandboxCustomTools, doneTool, subagentTool];
    const allowedTools = new Set(frontmatter.tools ?? toolNames);
    const hasSandboxTools = frontmatter.tools !== undefined;
    const tools = [
      ...activationTools,
      { name: "done" },
      { name: "subagents" },
      ...toolNames
        .filter(name => allowedTools.has(name))
        .filter(name => {
          if (name === "write" || name === "edit") return hasSandboxTools;
          return true;
        })
        .map(name => ({ name })),
    ];
    const loader = new DefaultResourceLoader({
      cwd,
      systemPromptOverride: () => agentPrompt,
    });
    await loader.reload();

    const sessionsDir = process.env.PI_AGENT_INGEST_URL
      ? `/tmp/pi-agent-transcripts-${process.pid}-${params.agent}-${runTimestamp}`
      : journalDir;

    const { session } = await createAgentSession({
      cwd,
      model: defaultModel,
      thinkingLevel: defaultModel.reasoning ? "medium" : "off",
      tools: tools as any,
      customTools: customTools as any,
      resourceLoader: loader,
      sessionManager: SessionManager.create(cwd, sessionsDir),
      settingsManager: SettingsManager.inMemory({
        compaction: { enabled: true },
        retry: {
          enabled: true,
          maxRetries: 5000,
          baseDelayMs: 2000,
          maxDelayMs: 24 * 60 * 60 * 1000,
        },
      }),
      authStorage,
      modelRegistry,
    });

    let output = "";
    let turnCount = 0;
    let consecutiveErrors = 0;
    const MAX_CONSECUTIVE_ERRORS = 5;
    const toolCallsUsed = new Set<string>();
    let doneCalled = false;
    let doneMessage = "";
    const doneVariables: Record<string, unknown> = {};

    const handle = journal.startAgent(params.agent, `${defaultModel.provider}/${defaultModel.id}`, {
      parentAgentId: params.parentAgentId,
      parentToolCallId: params.parentToolCallId,
    });
    const toolStartTimes = new Map<string, number>();

    session.subscribe((event: any) => {
      if (event.type === "message_update" && event.assistantMessageEvent?.type === "text_delta") {
        output += event.assistantMessageEvent.delta;
        process.stderr.write(event.assistantMessageEvent.delta);
      }
      if (event.type === "tool_execution_start") {
        toolCallsUsed.add(event.toolName ?? "?");
        if (event.toolCallId) toolStartTimes.set(event.toolCallId, Date.now());
        handle.toolCall(event.toolName ?? "?", event.args, event.toolCallId ?? "");
      }
      if (event.type === "tool_execution_end") {
        if (event.toolName === "done" && !event.isError) {
          doneCalled = true;
          const resultText = extractResultText(event.result);
          try {
            const parsed = JSON.parse(resultText);
            doneMessage = parsed.message ?? "";
            Object.assign(doneVariables, parsed.variables ?? {});
          } catch {
            doneMessage = resultText;
          }
        }
        if (event.isError) {
          consecutiveErrors++;
          const errorPreview = extractResultText(event.result) || "unknown error";
          process.stderr.write(`  [${params.agent}] Tool error (${event.toolName}): ${errorPreview.slice(0, 200)}\n`);
          if (event.toolCallId) {
            const started = toolStartTimes.get(event.toolCallId) ?? Date.now();
            handle.toolResult(event.toolCallId, false, Date.now() - started, errorPreview);
          }
          if (consecutiveErrors >= MAX_CONSECUTIVE_ERRORS) {
            process.stderr.write(`  [${params.agent}] Aborting: ${consecutiveErrors} consecutive tool errors\n`);
            output += `\nSTEP FAILED: Aborted after ${consecutiveErrors} consecutive tool errors`;
            session.abort();
          }
        } else {
          consecutiveErrors = 0;
          if (event.toolCallId) {
            const started = toolStartTimes.get(event.toolCallId) ?? Date.now();
            handle.toolResult(event.toolCallId, true, Date.now() - started, extractResultText(event.result));
          }
        }
      }
      if (event.type === "turn_end") {
        turnCount++;
        handle.turn();
        if (turnCount >= (params.maxTurns ?? 40)) session.abort();
      }
      if (event.type === "message_end") {
        if (event.message?.role === "assistant") {
          if (event.message.usage) handle.usage(event.message.usage);
          const extracted = extractAssistantText(event.message);
          if (extracted && extracted.length > output.length) output = extracted;
        }
      }
      if (event.type === "auto_retry_start") {
        handle.retryStart(event.attempt ?? 0, event.reason);
      }
      if (event.type === "auto_retry_end") {
        handle.retryEnd(event.attempt ?? 0, !event.error);
      }
    });

    await session.prompt(params.prompt);
    session.dispose();

    if (doneMessage || output) {
      journal.recordNarrative(params.agent, 1, doneMessage || output);
    }

    const success = !output.includes("STEP FAILED") && !output.includes("VERIFICATION FAILED") && doneCalled;
    handle.end(success);
    if (!sandboxLaunchedHere || !sandboxClient) {
      await journal.close(success);
      if (sandbox) sandbox.stop();
      return { output, summary: doneMessage || output.slice(0, 500), variables: doneVariables, success, toolCallsUsed: [...toolCallsUsed] };
    }
    let gitBranch: string | undefined;
    let gitPrUrl: string | undefined;
    const sgit = new SandboxGitOps(sandboxClient!);
    let gitCommits: any[] = [];
    try {
      gitBranch = await sgit.getCurrentBranch();
    } catch {
      const defaultBranch = params.sourceBranch || "main";
      const timestamp = Date.now().toString(36);
      gitBranch = "pi-agent-" + timestamp;
      try { await sgit.createBranch(gitBranch); } catch {  }
    }
    try {
      const sha = await sgit.commit(doneMessage || "Agent changes");
      if (sha) {
        gitCommits = [{ sha, message: doneMessage || "Agent changes" }];
        journal.commit("post-agent", sha, doneMessage || "Agent changes");
        process.stderr.write("[run-agent] committed " + sha + " on " + gitBranch + "\n");
      }
    } catch (e: any) {
      process.stderr.write("[run-agent] commit warning: " + e.message + "\n");
    }
    const pushToken = params.pushToken || "";
    if (pushToken && gitBranch) {
      try {
        await sgit.createBundle();
        const pushResult = pushBundleIsolated({
          bundleHostPath: (sandbox!.bundleHostDir || '/tmp') + "/run.bundle",
          remoteUrl: params.sourceRepoUrl!,
          branch: gitBranch,
          token: pushToken,
        });
        journal.pushDone(gitBranch, pushResult.ok, pushResult.output);
        if (!pushResult.ok) {
          process.stderr.write("[run-agent] push failed: " + pushResult.output.slice(0, 200) + "\n");
        } else {
          process.stderr.write("[run-agent] pushed " + gitBranch + "\n");
        }
      } catch (e: any) {
        process.stderr.write("[run-agent] push error: " + e.message + "\n");
        journal.pushDone(gitBranch, false, e.message);
      }
    }
    if (gitBranch && pushToken && params.sourceRepoUrl) {
      try {
        const provider = selectGitProvider();
        const resolvedToken = await provider.resolveToken();
        if (!resolvedToken) {
          process.stderr.write("[run-agent] no push token — skipping PR\n");
        } else {
          const { owner, repo } = parseRemote(params.sourceRepoUrl);
          const defaultBranch = params.sourceBranch || "main";
          const prResult = await provider.ensurePullRequest({
            remoteUrl: params.sourceRepoUrl!,
            head: gitBranch,
            base: defaultBranch,
            token: resolvedToken,
            title: (doneVariables?.pr_title as string) || (doneMessage || "").slice(0, 80) || "Agent changes",
            body: doneMessage || "Automated changes by Druppie agent.",
          });
          gitPrUrl = prResult.url;
          if (prResult.url) {
            journal.prEnsured(prResult.action, prResult.number, prResult.url);
            process.stderr.write("[run-agent] PR " + prResult.url + "\n");
          }
        }
      } catch (e: any) {
        process.stderr.write("[run-agent] PR error: " + e.message + "\n");
      }
    }
    try { await journal.close(success); } catch {}
    if (sandbox) sandbox.stop();
    const resultSummary = doneMessage || output.slice(0, 500);
    doneVariables["_branch"] = gitBranch;
    doneVariables["_pr_url"] = gitPrUrl;
    return {
      output,
      summary: resultSummary,
      variables: doneVariables,
      success,
      toolCallsUsed: [...toolCallsUsed],
    };
  } catch (err) {
    const errorMsg = err instanceof Error ? err.message : String(err);
    const errorStack = err instanceof Error ? (err.stack || "").slice(0, 500) : "";
    process.stderr.write(`[run-agent] Error: ${errorMsg}\n${errorStack}\n`);
    if (sandboxLaunchedHere && sandbox) {
      try { sandbox.stop(); } catch { /* ignore */ }
    }
    return { output: errorMsg, summary: `[run-agent] Error: ${errorMsg}`, variables: {}, success: false, toolCallsUsed: [] };
  }
}

interface AgentFrontmatter {
  tools?: string[];
  spawn?: string[];
  name?: string;
  description?: string;
  model?: string;
}

function parseFrontmatter(raw: string): AgentFrontmatter {
  const frontmatter: AgentFrontmatter = {};
  const match = raw.match(/^---\n([\s\S]*?)\n---/);
  if (!match) return frontmatter;
  for (const line of match[1].split("\n")) {
    const eqIdx = line.indexOf(":");
    if (eqIdx === -1) continue;
    const key = line.slice(0, eqIdx).trim();
    const val = line.slice(eqIdx + 1).trim();
    if (key === "tools") {
      if (val.startsWith("[")) {
        frontmatter.tools = JSON.parse(val.replace(/'/g, '"'));
      } else {
        frontmatter.tools = val.split(",").map(s => s.trim()).filter(Boolean);
      }
    } else if (key === "spawn") {
      if (val.startsWith("[")) {
        frontmatter.spawn = JSON.parse(val.replace(/'/g, '"'));
      }
    } else if (key === "name") {
      frontmatter.name = val;
    } else if (key === "description") {
      frontmatter.description = val;
    } else if (key === "model") {
      frontmatter.model = val;
    }
  }
  return frontmatter;
}

function loadAgentPrompt(agentName: string, projectRoot: string, cwd: string): { frontmatter: AgentFrontmatter; prompt: string } {
  const piRoot = projectRoot.replace(/\/dist$/, "");
  const dirs = [
    join(cwd, ".pi", "agents"),
    join(projectRoot, ".pi", "agents"),
    join(piRoot, ".pi", "agents"),
  ];
  for (const dir of dirs) {
    for (const ext of [".md", ".markdown"]) {
      const filePath = join(dir, `${agentName}${ext}`);
      if (existsSync(filePath)) {
        const raw = readFileSync(filePath, "utf-8");
        const frontmatter = parseFrontmatter(raw);
        const prompt = raw.replace(/^---\n[\s\S]*?\n---\n/, "").trim();
        return { frontmatter, prompt };
      }
    }
  }
  throw new Error(`Agent "${agentName}" not found. Searched: ${dirs.join(", ")}`);
}

function resolveModel(registry: ModelRegistry, spec: string): Model<Api> {
  if (spec.includes("/")) {
    const [prov, id] = spec.split("/", 2);
    const found = registry.find(prov, id);
    if (found) return found;
  } else {
    const found = registry.getAll().find((m) => m.id === spec);
    if (found) return found;
  }
  throw new Error(`Model not found: ${spec}`);
}

function extractAssistantText(message: any): string {
  if (!message) return "";
  if (typeof message.content === "string") return message.content;
  if (Array.isArray(message.content)) {
    return message.content
      .filter((b: any) => b?.type === "text" && typeof b.text === "string")
      .map((b: any) => b.text)
      .join("");
  }
  if (typeof message.text === "string") return message.text;
  return "";
}

function extractResultText(result: any): string {
  if (result == null) return "";
  if (Array.isArray(result?.content)) {
    const text = result.content
      .filter((p: any) => p?.type === "text" && typeof p.text === "string")
      .map((p: any) => p.text)
      .join("");
    if (text) return text;
  }
  if (typeof result?.output === "string" && result.output) return result.output;
  if (typeof result === "string") return result;
  try { return JSON.stringify(result) ?? ""; } catch { return ""; }
}

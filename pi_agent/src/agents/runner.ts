/**
 * Subagent runner — spawns isolated Pi agent sessions for focused subtasks.
 *
 * Each subagent gets its own in-memory session with:
 * - A scoped system prompt (loaded from .pi/agents/*.md)
 * - A configurable tool set
 * - A turn limit
 * - Full streaming output capture
 *
 * Supports any model provider registered on the ModelRegistry
 * (Anthropic, GLM, OpenAI-compatible, etc.)
 */
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import type { Model, Api } from "@mariozechner/pi-ai";
import {
  type AuthStorage as AuthStorageType,
  type ModelRegistry as ModelRegistryType,
  createAgentSession,
  createBashTool,
  createEditTool,
  createFindTool,
  createGrepTool,
  createLsTool,
  createReadTool,
  createWriteTool,
  DefaultResourceLoader,
  SessionManager,
  SettingsManager,
} from "@mariozechner/pi-coding-agent";
import type { AgentHandle, Journal } from "../journal.js";
import type { SandboxClient } from "../sandbox/client.js";
import { buildSandboxTools } from "../sandbox/tools-factory.js";

// ── Agent Definition ────────────────────────────────────────

export interface AgentDefinition {
  name: string;
  description: string;
  tools?: string[];
  /** Model ID — resolved via modelRegistry at runtime */
  model?: string;
  systemPrompt: string;
  source: "project" | "user";
  filePath: string;
}

// ── Agent Discovery ─────────────────────────────────────────

function parseFrontmatter(content: string): { frontmatter: Record<string, string>; body: string } {
  const match = content.match(/^---\n([\s\S]*?)\n---\n([\s\S]*)$/);
  if (!match) return { frontmatter: {}, body: content };

  const fm: Record<string, string> = {};
  for (const line of match[1].split("\n")) {
    const colon = line.indexOf(":");
    if (colon > 0) {
      fm[line.slice(0, colon).trim()] = line.slice(colon + 1).trim();
    }
  }
  return { frontmatter: fm, body: match[2] };
}

export function discoverAgents(cwd: string, extraDirs?: string[]): AgentDefinition[] {
  const agents: AgentDefinition[] = [];
  const dirs = [
    join(cwd, ".pi", "agents"),
    ...(extraDirs ?? []),
  ];

  for (const dir of dirs) {
    if (!existsSync(dir)) continue;
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (!entry.name.endsWith(".md")) continue;
      const filePath = join(dir, entry.name);
      const content = readFileSync(filePath, "utf-8");
      const { frontmatter, body } = parseFrontmatter(content);

      if (!frontmatter.name || !frontmatter.description) continue;

      agents.push({
        name: frontmatter.name,
        description: frontmatter.description,
        tools: frontmatter.tools?.split(",").map((t) => t.trim()).filter(Boolean),
        model: frontmatter.model,
        systemPrompt: body.trim(),
        source: "project",
        filePath,
      });
    }
  }
  return agents;
}

// ── Subagent Execution ──────────────────────────────────────

export interface SubagentResult {
  agentName: string;
  output: string;
  success: boolean;
  turnCount: number;
  error?: string;
}

export interface RunSubagentOptions {
  cwd: string;
  /** Pre-configured AuthStorage (with API keys already set) */
  authStorage: AuthStorageType;
  /** Pre-configured ModelRegistry (with providers already registered) */
  modelRegistry: ModelRegistryType;
  /** Resolved default model to use when agent doesn't specify one */
  defaultModel: Model<Api>;
  maxTurns?: number;
  onOutput?: (delta: string) => void;
  /** Custom directory for session logs (default: ~/.pi/agent/sessions/) */
  sessionsDir?: string;
  /** When set, all tool operations route to this sandbox daemon instead of local fs. */
  sandboxClient?: SandboxClient;
  /** Optional journal — receives per-subagent event stream for the run transcript. */
  journal?: Journal;
  /** Extra ToolDefinitions to register on top of the sandbox-tool set (e.g.
   * spawn_parallel_explorers for the explore flow's router). Passed straight
   * through to pi's customTools. Their names are added to the active-tools list
   * so the LLM actually sees them. */
  extraCustomTools?: any[];
}

/** Run a single subagent with an in-process Pi session. */
export async function runSubagent(
  agent: AgentDefinition,
  prompt: string,
  options: RunSubagentOptions
): Promise<SubagentResult> {
  const { cwd, authStorage, modelRegistry, defaultModel, maxTurns = 30, onOutput, sessionsDir, sandboxClient, journal, extraCustomTools } = options;

  // Resolve model: agent-specific or default
  // Agent model field can be "provider/id" (e.g. "glm-coding/glm-4.5-air") or just "id"
  let model: Model<Api> = defaultModel;
  if (agent.model) {
    const found = resolveModel(modelRegistry, agent.model);
    if (found) {
      model = found;
    } else {
      console.warn(`[${agent.name}] Model "${agent.model}" not found in registry, using default`);
    }
  }

  // Tools — honor the frontmatter list exactly (previously: any write tool
  // silently granted the full write+bash toolset). In sandbox mode, pass our
  // remote-operation ToolDefinitions via `customTools` (they replace pi's
  // built-ins by name in the tool registry) and use `tools` only to signal
  // which names are active.
  const toolNames = agent.tools ?? ["read", "bash", "edit", "write"];
  const sandboxTools = sandboxClient ? buildSandboxTools(sandboxClient, toolNames) : undefined;
  // (diagnostic removed — the sandboxed tool path is now verified)
  const baseTools = sandboxTools ? sandboxTools.activationTools : buildLocalTools(toolNames, cwd);
  const tools = extraCustomTools?.length
    ? [...baseTools, ...extraCustomTools.map((t: any) => ({ name: t.name }))]
    : baseTools;
  const customTools = [
    ...(sandboxTools?.customTools ?? []),
    ...(extraCustomTools ?? []),
  ];

  // Resource loader with system prompt
  const loader = new DefaultResourceLoader({
    cwd,
    systemPromptOverride: () => agent.systemPrompt,
  });
  await loader.reload();

  // Session
  const { session } = await createAgentSession({
    cwd,
    model,
    thinkingLevel: model.reasoning ? "medium" : "off",
    tools: tools as any,
    customTools: customTools as any,
    resourceLoader: loader,
    sessionManager: sessionsDir ? SessionManager.create(cwd, sessionsDir) : SessionManager.create(cwd),
    settingsManager: SettingsManager.inMemory({
      compaction: { enabled: true },
      // Keep retrying essentially "as long as the sandbox is alive". The real
      // stop condition is the sandbox's wall-clock timeout (default 24h) —
      // pi's retry count only has to not run out before that fires.
      // maxDelayMs = 24h so pi honours any server-requested Retry-After up to
      // a full day (some rate-limited providers request hours).
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

  const handle: AgentHandle | undefined = journal?.startAgent(agent.name, `${model.provider}/${model.id}`);
  const toolStartTimes = new Map<string, number>();

  session.subscribe((event) => {
    if (event.type === "message_update" && event.assistantMessageEvent.type === "text_delta") {
      const delta = event.assistantMessageEvent.delta;
      output += delta;
      onOutput?.(delta);
    }
    if (event.type === "tool_execution_start") {
      const ev = event as { toolName?: string; toolCallId?: string; input?: unknown };
      if (ev.toolCallId) toolStartTimes.set(ev.toolCallId, Date.now());
      handle?.toolCall(ev.toolName ?? "?", ev.input, ev.toolCallId ?? "");
    }
    if (event.type === "tool_execution_end") {
      const ev = event as any;
      if (ev.isError) {
        consecutiveErrors++;
        const errorPreview = extractResultPreview(ev.result, 400) || "unknown error";
        console.error(`  [${agent.name}] Tool error (${ev.toolName}): ${errorPreview.slice(0, 200)}`);
        if (handle && ev.toolCallId) {
          const started = toolStartTimes.get(ev.toolCallId) ?? Date.now();
          handle.toolResult(ev.toolCallId, false, Date.now() - started, errorPreview);
        }
        if (consecutiveErrors >= MAX_CONSECUTIVE_ERRORS) {
          console.error(`  [${agent.name}] Aborting: ${consecutiveErrors} consecutive tool errors (stuck in loop)`);
          output += `\nSTEP FAILED: Aborted after ${consecutiveErrors} consecutive tool errors`;
          session.abort();
        }
      } else {
        consecutiveErrors = 0;
        if (handle && ev.toolCallId) {
          const started = toolStartTimes.get(ev.toolCallId) ?? Date.now();
          const preview = extractResultPreview(ev.result, 800);
          handle.toolResult(ev.toolCallId, true, Date.now() - started, preview);
        }
      }
    }
    if (event.type === "turn_end") {
      turnCount++;
      handle?.turn();
      if (turnCount >= maxTurns) session.abort();
    }
    // Capture token usage from completed assistant messages
    if (event.type === "message_end") {
      const ev = event as any;
      if (ev.message?.role === "assistant" && ev.message?.usage) {
        handle?.usage(ev.message.usage);
      }
    }
    // Retry events — pi emits these when a provider request is auto-retried
    if ((event as any).type === "auto_retry_start") {
      const ev = event as any;
      handle?.retryStart(ev.attempt ?? 0, ev.reason);
    }
    if ((event as any).type === "auto_retry_end") {
      const ev = event as any;
      handle?.retryEnd(ev.attempt ?? 0, !ev.error);
    }
  });

  try {
    await session.prompt(prompt);
    session.dispose();

    const success = !output.includes("STEP FAILED") && !output.includes("VERIFICATION FAILED");
    handle?.end(success);
    return { agentName: agent.name, output, success, turnCount };
  } catch (err) {
    session.dispose();
    const errorMsg = err instanceof Error ? err.message : String(err);
    handle?.end(false, errorMsg);
    return {
      agentName: agent.name,
      output: output + `\n\nError: ${errorMsg}`,
      success: false,
      turnCount,
      error: errorMsg,
    };
  }
}

/** Run multiple subagents in parallel, all sharing the same cwd. */
export async function runSubagentsParallel(
  agents: Array<{ agent: AgentDefinition; prompt: string }>,
  options: RunSubagentOptions
): Promise<SubagentResult[]> {
  const MAX_CONCURRENCY = 4;
  const results: SubagentResult[] = new Array(agents.length);
  let nextIndex = 0;

  const workers = Array.from({ length: Math.min(MAX_CONCURRENCY, agents.length) }, async () => {
    while (true) {
      const idx = nextIndex++;
      if (idx >= agents.length) return;
      const { agent, prompt } = agents[idx];
      const prefix = `[${agent.name}] `;
      results[idx] = await runSubagent(agent, prompt, {
        ...options,
        onOutput: (delta) => options.onOutput?.(prefix + delta),
      });
    }
  });

  await Promise.all(workers);
  return results;
}

// ── Helpers ─────────────────────────────────────────────────

/**
 * Best-effort textual preview of a tool result. pi-coding-agent tools return
 * MCP-style `{content: [{type: "text", text: ...}]}`, but custom tools
 * (like spawn_parallel_explorers) return `{output, details}`. Grab whichever
 * looks useful and cap the length.
 */
function extractResultPreview(result: any, maxLen = 800): string {
  if (result == null) return "";
  // MCP-style: {content: [{type:"text", text:"..."}]}
  const content = Array.isArray(result?.content) ? result.content : null;
  if (content) {
    const text = content
      .filter((p: any) => p && p.type === "text" && typeof p.text === "string")
      .map((p: any) => p.text)
      .join("");
    if (text) return text.slice(0, maxLen);
  }
  // Custom-tool shape used by spawn-tool.ts: `{output: string, details: any}`.
  if (typeof result?.output === "string" && result.output) {
    return result.output.slice(0, maxLen);
  }
  // Plain string.
  if (typeof result === "string") return result.slice(0, maxLen);
  // Fallback: stringify the whole thing so the UI shows *something*.
  try {
    const json = JSON.stringify(result);
    if (json) return json.slice(0, maxLen);
  } catch {
    /* ignore */
  }
  return "";
}

/**
 * Build the exact set of tools named in the agent's frontmatter. No more,
 * no less. Unknown names are dropped with a warning.
 */
function buildLocalTools(toolNames: string[], cwd: string): any[] {
  const want = new Set(toolNames.map((t) => t.trim()).filter(Boolean));
  const tools: any[] = [];
  if (want.has("read")) tools.push(createReadTool(cwd));
  if (want.has("write")) tools.push(createWriteTool(cwd));
  if (want.has("edit")) tools.push(createEditTool(cwd));
  if (want.has("ls")) tools.push(createLsTool(cwd));
  if (want.has("grep")) tools.push(createGrepTool(cwd));
  if (want.has("find")) tools.push(createFindTool(cwd));
  if (want.has("bash")) tools.push(createBashTool(cwd));
  for (const name of want) {
    if (!["read", "write", "edit", "ls", "grep", "find", "bash"].includes(name)) {
      console.warn(`[tools] unknown tool name "${name}" ignored`);
    }
  }
  return tools;
}

/** Resolve a model by "provider/id" or search all providers for "id". */
function resolveModel(registry: ModelRegistryType, spec: string): Model<Api> | undefined {
  if (spec.includes("/")) {
    const [provider, id] = spec.split("/", 2);
    return registry.find(provider, id);
  }
  // Search all models for a matching ID
  return registry.getAll().find((m) => m.id === spec);
}

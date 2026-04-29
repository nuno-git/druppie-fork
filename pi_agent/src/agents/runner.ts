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
  /** Whether this agent can spawn subagents */
  spawn_subagents?: boolean;
  /** List of agent names this agent is allowed to spawn */
  allowed_subagents?: string[];
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

/** Parse a frontmatter value that may be a JSON array, a YAML-flow array,
 * or a comma-separated list. Previously the runner split raw strings by
 * comma and left the brackets + quotes intact, so e.g.
 *   tools: ["read", "grep", "find", "bash"]
 * parsed as the four literal strings `["read"`, `"grep"`, `"find"`, `"bash"]`
 * which then failed every `want.has("read")` check in buildSandboxTools —
 * silently giving every subagent zero tools. That's the root cause of the
 * "explorer emits XML tool calls in text" failure we spent hours on.
 */
function parseFrontmatterList(raw: string | undefined): string[] | undefined {
  if (!raw) return undefined;
  const trimmed = raw.trim();
  // Try JSON first — handles ["a","b","c"] and even ['a','b'] after quote swap.
  if (trimmed.startsWith("[") && trimmed.endsWith("]")) {
    try {
      const parsed = JSON.parse(trimmed.replace(/'/g, '"'));
      if (Array.isArray(parsed)) return parsed.map(String).map((s) => s.trim()).filter(Boolean);
    } catch {
      // Fall through to manual parse.
    }
    // Manual: strip brackets, split, strip quotes/whitespace.
    return trimmed
      .slice(1, -1)
      .split(",")
      .map((t) => t.trim().replace(/^["']|["']$/g, ""))
      .filter(Boolean);
  }
  // Bare comma-separated form: `tools: read, grep, find, bash`
  return trimmed
    .split(",")
    .map((t) => t.trim().replace(/^["']|["']$/g, ""))
    .filter(Boolean);
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
        tools: parseFrontmatterList(frontmatter.tools),
        model: frontmatter.model,
        spawn_subagents: frontmatter.spawn_subagents === "true",
        allowed_subagents: parseFrontmatterList(frontmatter.allowed_subagents),
        systemPrompt: body.trim(),
        source: "project",
        filePath,
      });
    }
  }
  return agents;
}

// ── Summary & Variable Extraction ──────────────────────────

/**
 * Extract the ## Summary section from agent output.
 *
 * Looks for a section starting with "## Summary" and returns its content
 * until the next "##" header or end of string.
 *
 * @param output - Full agent output
 * @returns Extracted summary text, or empty string if not found
 */
export function extractSummary(output: string): string {
  const summaryMatch = output.match(/## Summary\n([\s\S]+?)(?=\n##|\n*$)/);
  if (!summaryMatch) return "";

  let summary = summaryMatch[1].trim();

  // Remove the "## Variables" section if present (we parse that separately)
  const varMatch = summary.match(/([\s\S]+?)\n## Variables\n/);
  if (varMatch) {
    summary = varMatch[1].trim();
  }

  return summary;
}

/**
 * Extract variables from the ## Variables section of an agent summary.
 *
 * Parses key: value pairs from the variables section.
 *
 * @param summary - Agent summary (may include ## Variables section)
 * @returns Map of variable names to values
 */
export function extractVariables(summary: string): Map<string, string> {
  const vars = new Map<string, string>();
  const varMatch = summary.match(/## Variables\n([\s\S]+?)(?=\n##|\n*$)/);

  if (!varMatch) return vars;

  const varText = varMatch[1];
  for (const line of varText.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;

    // Parse "key: value" format
    const colonIndex = trimmed.indexOf(":");
    if (colonIndex > 0) {
      const key = trimmed.slice(0, colonIndex).trim();
      const value = trimmed.slice(colonIndex + 1).trim();
      if (key) {
        vars.set(key, value);
      }
    }
  }

  return vars;
}

/**
 * Parse agent result into structured data for flow consumption.
 *
 * For agents that output structured data in code blocks (e.g., ```json),
 * this function attempts to parse and return it.
 *
 * @param output - Full agent output
 * @returns Parsed structured data, or undefined if not found
 */
export function extractStructuredData<T = unknown>(output: string): T | undefined {
  // Try to find a JSON code block
  const jsonMatch = output.match(/```(?:json)?\s*\n([\s\S]+?)\n```/);
  if (!jsonMatch) return undefined;

  try {
    return JSON.parse(jsonMatch[1]) as T;
  } catch {
    return undefined;
  }
}

// ── Subagent Execution ──────────────────────────────────────

export interface SubagentResult {
  agentName: string;
  output: string;
  success: boolean;
  turnCount: number;
  error?: string;
  /** Extracted summary section from the output */
  summary?: string;
  /** Parsed variables from the summary */
  variables?: Map<string, string>;
  /** Set of tool names that were actually invoked during this session */
  toolCallsUsed: Set<string>;
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
  /** Optional structural metadata attached to this subagent's start event.
   *  Set by flow orchestrators (e.g. tdd's executeWaves) so the UI can
   *  group subagents by wave / step instead of inferring from timestamps. */
  meta?: Record<string, unknown>;
}

/** Run a single subagent with an in-process Pi session. */
export async function runSubagent(
  agent: AgentDefinition,
  prompt: string,
  options: RunSubagentOptions
): Promise<SubagentResult> {
  const { cwd, authStorage, modelRegistry, defaultModel, maxTurns = 30, onOutput, sessionsDir, sandboxClient, journal, extraCustomTools, meta } = options;

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
  const toolCallsUsed = new Set<string>();

  const handle: AgentHandle | undefined = journal?.startAgent(agent.name, `${model.provider}/${model.id}`, meta);
  const toolStartTimes = new Map<string, number>();

  session.subscribe((event) => {
    if (event.type === "message_update" && event.assistantMessageEvent.type === "text_delta") {
      const delta = event.assistantMessageEvent.delta;
      output += delta;
      onOutput?.(delta);
    }
    if (event.type === "tool_execution_start") {
      const ev = event as { toolName?: string; toolCallId?: string; args?: unknown; input?: unknown };
      toolCallsUsed.add(ev.toolName ?? "?");
      if (ev.toolCallId) toolStartTimes.set(ev.toolCallId, Date.now());
      const toolArgs = ev.args !== undefined ? ev.args : ev.input;
      handle?.toolCall(ev.toolName ?? "?", toolArgs, ev.toolCallId ?? "");
    }
    if (event.type === "tool_execution_end") {
      const ev = event as any;
      if (ev.isError) {
        consecutiveErrors++;
        const errorPreview = extractResultPreview(ev.result) || "unknown error";
        // Console log stays bounded so one giant stderr line doesn't blow
        // up the terminal — but the stored preview (sent to the journal
        // below) is the full thing.
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
          const preview = extractResultPreview(ev.result);
          handle.toolResult(ev.toolCallId, true, Date.now() - started, preview);
        }
      }
    }
    if (event.type === "turn_end") {
      turnCount++;
      handle?.turn();
      if (turnCount >= maxTurns) session.abort();
    }
    // Capture token usage AND defensive-capture the final assistant text
    // from the complete message. Relying only on text_delta events misses
    // turns where the model streams via a different path (e.g. reasoning
    // mode where content arrives in one chunk, or provider adapters that
    // don't emit per-character deltas for the final turn). Here we read
    // the finished message and overwrite `output` if it gives us more text
    // than we captured via text_delta — taking the longer of the two.
    if (event.type === "message_end") {
      const ev = event as any;
      if (ev.message?.role === "assistant") {
        if (ev.message.usage) handle?.usage(ev.message.usage);
        const extracted = extractAssistantText(ev.message);
        if (extracted && extracted.length > output.length) {
          output = extracted;
        }
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

    // Extract summary and variables
    const summary = extractSummary(output);
    const variables = extractVariables(output);

    return { agentName: agent.name, output, success, turnCount, summary, variables, toolCallsUsed };
  } catch (err) {
    session.dispose();
    const errorMsg = err instanceof Error ? err.message : String(err);
    handle?.end(false, errorMsg);

    // Extract summary and variables even on error
    const summary = extractSummary(output);
    const variables = extractVariables(output);

    return {
      agentName: agent.name,
      output: output + `\n\nError: ${errorMsg}`,
      success: false,
      turnCount,
      error: errorMsg,
      summary,
      variables,
      toolCallsUsed,
    };
  }
}

/** Run multiple subagents in parallel, all sharing the same cwd.
 *
 * Each task may carry its own `meta` — that lands on the subagent's
 * `subagent_start` event so the UI can render the wave grouping that
 * the planner actually asked for.
 */
export async function runSubagentsParallel(
  agents: Array<{ agent: AgentDefinition; prompt: string; meta?: Record<string, unknown> }>,
  options: RunSubagentOptions
): Promise<SubagentResult[]> {
  const MAX_CONCURRENCY = 4;
  const results: SubagentResult[] = new Array(agents.length);
  let nextIndex = 0;

  const workers = Array.from({ length: Math.min(MAX_CONCURRENCY, agents.length) }, async () => {
    while (true) {
      const idx = nextIndex++;
      if (idx >= agents.length) return;
      const { agent, prompt, meta } = agents[idx];
      const prefix = `[${agent.name}] `;
      results[idx] = await runSubagent(agent, prompt, {
        ...options,
        onOutput: (delta) => options.onOutput?.(prefix + delta),
        meta: meta ?? options.meta,
      });
    }
  });

  await Promise.all(workers);
  return results;
}

// ── Helpers ─────────────────────────────────────────────────

/**
 * Pull the plain text out of an assistant AgentMessage regardless of how
 * the provider laid it out. pi-agent-core messages typically carry a
 * `content` array of `{type, text}` blocks (Anthropic-style). Some
 * providers put a flat string in `content`. Some surface `text` directly.
 * We try them all and return the concatenated text — used as a safety-net
 * when text_delta streaming didn't capture the final turn (e.g. reasoning
 * mode finalising in one chunk).
 */
function extractAssistantText(message: any): string {
  if (!message) return "";
  if (typeof message.content === "string") return message.content;
  if (Array.isArray(message.content)) {
    return message.content
      .filter((b: any) => b && b.type === "text" && typeof b.text === "string")
      .map((b: any) => b.text)
      .join("");
  }
  if (typeof message.text === "string") return message.text;
  return "";
}

/**
 * Full textual view of a tool result. pi-coding-agent tools return
 * MCP-style `{content: [{type: "text", text: ...}]}`, but custom tools
 * (like spawn_parallel_explorers) return `{output, details}`. We return
 * the whole thing verbatim — this is the exact context the LLM saw
 * after the tool ran, and we don't truncate LLM-facing data.
 */
function extractResultPreview(result: any): string {
  if (result == null) return "";
  // MCP-style: {content: [{type:"text", text:"..."}]}
  const content = Array.isArray(result?.content) ? result.content : null;
  if (content) {
    const text = content
      .filter((p: any) => p && p.type === "text" && typeof p.text === "string")
      .map((p: any) => p.text)
      .join("");
    if (text) return text;
  }
  // Custom-tool shape used by spawn-tool.ts: `{output: string, details: any}`.
  if (typeof result?.output === "string" && result.output) {
    return result.output;
  }
  // Plain string.
  if (typeof result === "string") return result;
  // Fallback: stringify the whole thing so the UI shows *something*.
  try {
    const json = JSON.stringify(result);
    if (json) return json;
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

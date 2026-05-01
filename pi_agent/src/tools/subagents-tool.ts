/**
 * `subagents` tool — pi-subagents compatible API surface.
 *
 * Replaces the old `spawn_subagents` tool with full support for:
 * - **Single**: `{agent, task}` — run one subagent
 * - **Parallel**: `{tasks: [{agent, task}]}` — run multiple concurrently (max 4)
 * - **Chain**: `{chain: [{agent, task?}]}` — sequential pipeline with `{previous}` / `{task}` templates
 *
 * Matches the community pi-subagents extension so agent .md files work
 * identically in both `pi` CLI and our programmatic runner.
 */
import { Type } from "@sinclair/typebox";
import type { AgentDefinition, RunSubagentOptions, SubagentResult } from "../agents/runner.js";
import { runSubagent, runSubagentsParallel } from "../agents/runner.js";

// ── Context ─────────────────────────────────────────────────

export interface SubagentsContext {
  /** All discovered agent definitions, keyed by name. */
  agentMap: Map<string, AgentDefinition>;
  /** Agent names the calling agent is allowed to invoke. */
  allowedAgents: string[];
  /** Base options forwarded to every spawned subagent. */
  baseOpts: RunSubagentOptions;
  /** Hard cap on parallel subagents per call. Default 4. */
  maxParallel?: number;
}

// ── Parameter Schema ────────────────────────────────────────

const SubagentParams = Type.Object({
  agent: Type.Optional(Type.String({ description: "Agent name (SINGLE mode)" })),
  task: Type.Optional(Type.String({ description: "Task for the agent (SINGLE mode)" })),
  tasks: Type.Optional(
    Type.Array(
      Type.Object({
        agent: Type.String({ description: "Agent name" }),
        task: Type.String({ description: "Task description" }),
      }),
      { description: "PARALLEL mode: run multiple agents concurrently" },
    ),
  ),
  chain: Type.Optional(
    Type.Array(
      Type.Object({
        agent: Type.Optional(Type.String({ description: "Agent name for this step" })),
        task: Type.Optional(
          Type.String({
            description: "Task template. Use {previous} for prior step output, {task} for original task",
          }),
        ),
        parallel: Type.Optional(
          Type.Array(
            Type.Object({
              agent: Type.String(),
              task: Type.Optional(Type.String()),
            }),
            { description: "Parallel tasks within this chain step" },
          ),
        ),
      }),
      { description: "CHAIN mode: sequential pipeline" },
    ),
  ),
  context: Type.Optional(
    Type.String({
      enum: ["fresh", "fork"],
      description: "Context mode: fresh (default) or fork (inherit parent conversation)",
    }),
  ),
});

// ── Helpers ─────────────────────────────────────────────────

interface ResultEntry {
  agent: string;
  success: boolean;
  output: string;
  error?: string;
}

function resolveAgent(name: string, ctx: SubagentsContext): AgentDefinition | string {
  const def = ctx.agentMap.get(name);
  if (!def) return `Unknown agent: "${name}". Available: ${Array.from(ctx.agentMap.keys()).join(", ")}`;
  if (!ctx.allowedAgents.includes(name))
    return `Agent "${name}" not in allowed_subagents list. Allowed: ${ctx.allowedAgents.join(", ")}`;
  return def;
}

function resultFromSub(r: SubagentResult): ResultEntry {
  return {
    agent: r.agentName,
    success: r.success,
    output: r.output.slice(0, 4000),
    ...(r.error ? { error: r.error } : {}),
  };
}

function toolResponse(count: number, results: ResultEntry[]) {
  return {
    content: [{ type: "text" as const, text: JSON.stringify({ count, results }) }],
  };
}

function errorResponse(agent: string, msg: string): ResultEntry {
  return { agent, success: false, output: "", error: msg };
}

// ── Factory ─────────────────────────────────────────────────

export function createSubagentsTool(ctx: SubagentsContext): any {
  const maxParallel = ctx.maxParallel ?? 4;

  return {
    name: "subagents",
    label: "Run Subagents",
    description:
      "Spawn subagents to execute tasks. Supports three modes:\n" +
      "- Single: {agent, task} for one agent\n" +
      "- Parallel: {tasks: [{agent, task}]} for concurrent execution\n" +
      "- Chain: {chain: [{agent, task}]} for sequential pipeline with {previous} variable\n" +
      "Blocks until all finish.",
    promptSnippet: "subagents: delegate work to specialized agents",
    parameters: SubagentParams,

    async execute(toolCallId: string, params: Record<string, unknown>) {
      // ── PARALLEL mode ──────────────────────────────────
      if (params.tasks) {
        const tasks = (params.tasks as Array<{ agent: string; task: string }>).slice(0, maxParallel);
        const results: ResultEntry[] = [];

        // Validate upfront so we report all errors at once
        const specs: Array<{ agent: AgentDefinition; prompt: string }> = [];
        for (const t of tasks) {
          const resolved = resolveAgent(t.agent, ctx);
          if (typeof resolved === "string") {
            results.push(errorResponse(t.agent, resolved));
            continue;
          }
          specs.push({ agent: resolved, prompt: t.task });
        }

        // Run valid specs in parallel
        if (specs.length > 0) {
          const subResults = await runSubagentsParallel(specs, ctx.baseOpts);
          for (const r of subResults) {
            results.push(resultFromSub(r));
          }
        }

        return toolResponse(results.length, results);
      }

      // ── CHAIN mode ─────────────────────────────────────
      if (params.chain) {
        const steps = params.chain as Array<{
          agent?: string;
          task?: string;
          parallel?: Array<{ agent: string; task?: string }>;
        }>;
        const results: ResultEntry[] = [];
        let previousOutput = "";
        const originalTask = params.task as string | undefined ?? "";

        for (let i = 0; i < steps.length; i++) {
          const step = steps[i];

          // Expand template variables in task
          const expand = (tpl: string | undefined): string => {
            if (!tpl) return originalTask;
            return tpl
              .replace(/\{previous\}/g, previousOutput)
              .replace(/\{task\}/g, originalTask);
          };

          // Parallel step within chain
          if (step.parallel && step.parallel.length > 0) {
            const pSpecs: Array<{ agent: AgentDefinition; prompt: string }> = [];
            const pErrors: ResultEntry[] = [];

            for (const pt of step.parallel) {
              const agentName = pt.agent;
              const resolved = resolveAgent(agentName, ctx);
              if (typeof resolved === "string") {
                pErrors.push(errorResponse(agentName, resolved));
                continue;
              }
              pSpecs.push({ agent: resolved, prompt: expand(pt.task) });
            }

            let parallelOutputs: string[] = [];
            if (pSpecs.length > 0) {
              const subResults = await runSubagentsParallel(pSpecs, ctx.baseOpts);
              for (const r of subResults) {
                results.push(resultFromSub(r));
                parallelOutputs.push(r.output);
              }
            }
            for (const e of pErrors) results.push(e);
            previousOutput = parallelOutputs.join("\n---\n");
            continue;
          }

          // Sequential step
          const agentName = step.agent ?? "";
          if (!agentName) {
            results.push(errorResponse("(unnamed)", `Chain step ${i + 1} has no agent name`));
            previousOutput = "";
            continue;
          }

          const resolved = resolveAgent(agentName, ctx);
          if (typeof resolved === "string") {
            results.push(errorResponse(agentName, resolved));
            previousOutput = "";
            continue;
          }

          const prompt = expand(step.task);
          try {
            const r = await runSubagent(resolved, prompt, ctx.baseOpts);
            results.push(resultFromSub(r));
            previousOutput = r.output;
          } catch (err) {
            const msg = err instanceof Error ? err.message : String(err);
            results.push(errorResponse(agentName, msg));
            previousOutput = "";
          }
        }

        return toolResponse(results.length, results);
      }

      // ── SINGLE mode ────────────────────────────────────
      const agentName = params.agent as string | undefined;
      if (!agentName) {
        return toolResponse(1, [errorResponse("(missing)", "No agent name provided. Use {agent, task} for single mode.")]);
      }

      const resolved = resolveAgent(agentName, ctx);
      if (typeof resolved === "string") {
        return toolResponse(1, [errorResponse(agentName, resolved)]);
      }

      const task = (params.task as string) ?? "";
      const r = await runSubagent(resolved, task, ctx.baseOpts);
      return toolResponse(1, [resultFromSub(r)]);
    },
  };
}

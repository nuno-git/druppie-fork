/**
 * `spawn_subagents` custom tool for the TDD flow.
 *
 * Allows agents with `spawn_subagents: true` (e.g. planner) to spawn
 * subagents (e.g. builders) in parallel. The tool blocks until all
 * subagents finish, then returns their outputs as JSON.
 *
 * The spawning agent is responsible for sequencing — this tool is a
 * single batch call. Call it multiple times for sequential batches.
 */
import { Type } from "@sinclair/typebox";
import type { AgentDefinition, RunSubagentOptions } from "../../agents/runner.js";
import { runSubagentsParallel } from "../../agents/runner.js";

export interface SpawnSubagentsContext {
  /** All discovered agent definitions, keyed by name. */
  agentMap: Map<string, AgentDefinition>;
  /** Agent names the spawning agent is allowed to invoke. */
  allowedAgents: string[];
  /** Base options to pass through to each spawned subagent. */
  baseOpts: RunSubagentOptions;
  /** Hard cap on parallel subagents per call. Default 4. */
  maxParallel?: number;
  /** Mutable ref — caller sets to current agent's ID before running the parent.
   *  Used to stamp parentAgentId on each spawned child for UI hierarchy. */
  parentRef?: { current?: string };
  /** Mutable output — after execute(), contains the union of all child toolCallsUsed.
   *  The FlowExecutor reads this to check if any child called "done". */
  childToolCallsUsed?: Set<string>;
}

const SpawnParams = Type.Object({
  tasks: Type.Array(
    Type.Object({
      agent: Type.String({
        description: "Name of the agent to spawn (e.g. 'builder'). Must be in the allowed_subagents list.",
      }),
      prompt: Type.String({
        description: "Self-contained task prompt for this subagent.",
      }),
    }),
    { minItems: 1 },
  ),
});

/**
 * Build the spawn_subagents ToolDefinition bound to a specific context.
 */
export function createSpawnSubagentsTool(ctx: SpawnSubagentsContext): any {
  const maxParallel = ctx.maxParallel ?? 4;

  return {
    name: "spawn_subagents",
    label: "Spawn subagents",
    description:
      "Spawn N subagents in parallel, each given an independent task. " +
      "Blocks until all finish, then returns {results: [{agent, success, output}]}. " +
      "Each subagent runs in isolation with its own session. " +
      "Use for parallelizable work (e.g. multiple builders touching different files). " +
      "For sequential work, call this tool multiple times, waiting for each batch to finish.",
    promptSnippet: "spawn_subagents: fan out subagents to execute independent tasks in parallel.",
    parameters: SpawnParams,
    async execute(
      toolCallId: string,
      params: { tasks: Array<{ agent: string; prompt: string }> },
    ) {
      const tasks = params.tasks.slice(0, maxParallel);
      const errors: string[] = [];

      const parentAgentId = ctx.parentRef?.current;
      const specs = tasks.map((t) => {
        const agentDef = ctx.agentMap.get(t.agent);
        if (!agentDef) {
          errors.push(`Unknown agent: "${t.agent}". Available: ${Array.from(ctx.agentMap.keys()).join(", ")}`);
          return null;
        }
        if (!ctx.allowedAgents.includes(t.agent)) {
          errors.push(`Agent "${t.agent}" not in allowed_subagents list. Allowed: ${ctx.allowedAgents.join(", ")}`);
          return null;
        }
        return {
          agent: agentDef,
          prompt: t.prompt,
          meta: {
            parentAgentId,
            parentToolCallId: toolCallId,
          },
        };
      });

      if (errors.length > 0) {
        return {
          output: JSON.stringify({ success: false, errors }),
          details: { errors },
        };
      }

      const validSpecs = specs.filter(Boolean) as Array<{ agent: AgentDefinition; prompt: string; meta?: Record<string, unknown> }>;
      const subResults = await runSubagentsParallel(validSpecs, ctx.baseOpts);

      const mergedToolCalls = ctx.childToolCallsUsed ?? new Set<string>();
      for (const r of subResults) {
        r.toolCallsUsed?.forEach(t => mergedToolCalls.add(t));
      }
      ctx.childToolCallsUsed = mergedToolCalls;

      const results = tasks.map((t, i) => ({
        agent: t.agent,
        success: subResults[i].success,
        output: subResults[i].output.slice(0, 2000),
        ...(subResults[i].error ? { error: subResults[i].error } : {}),
      }));

      return {
        output: JSON.stringify({ count: results.length, results }),
        details: { count: results.length },
      };
    },
  };
}

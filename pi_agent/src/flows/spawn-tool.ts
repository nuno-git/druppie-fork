/**
 * `spawn_parallel_explorers` custom tool for the explore flow.
 *
 * Gives the router agent a way to fan out N explorer subagents in parallel,
 * each given a scoped sub-question. The tool blocks until all finish, then
 * returns their outputs as a single JSON result so the router can read the
 * findings in its next turn and decide whether to spawn more or conclude.
 *
 * The router is responsible for the loop. This tool is a single step.
 */
import { Type } from "@sinclair/typebox";
import type { AgentDefinition, RunSubagentOptions } from "../agents/runner.js";
import { runSubagentsParallel } from "../agents/runner.js";

export interface SpawnToolContext {
  /** Explorer agent loaded from .pi/agents/explorer.md. */
  explorer: AgentDefinition;
  /** Base options to pass through to each spawned explorer (sandbox client,
   * journal, model registry, etc). */
  baseOpts: RunSubagentOptions;
  /** Hard cap on how many explorers can run in parallel in a single call.
   * Keeps a confused router from spawning 50 agents. Default 6. */
  maxParallel?: number;
  /** Hook so the router's journal records each round for the narrative. */
  onRoundComplete?: (round: number, results: Array<{ id: string; output: string; success: boolean }>) => void;
}

const SpawnParams = Type.Object({
  tasks: Type.Array(
    Type.Object({
      id: Type.String({
        description: "Short slug used to key the results in the response (e.g. 'auth-mechanism', 'test-utils').",
      }),
      prompt: Type.String({
        description: "Self-contained exploration prompt for this explorer — what it should look at and what answer it should return.",
      }),
    }),
    { minItems: 1 },
  ),
});

/**
 * Build the spawn_parallel_explorers ToolDefinition bound to a specific
 * explorer agent + base options. Returns `any` because we don't re-export
 * pi-coding-agent's ToolDefinition type.
 */
export function createSpawnParallelExplorersTool(ctx: SpawnToolContext): any {
  const maxParallel = ctx.maxParallel ?? 6;
  let roundIndex = 0;

  return {
    name: "spawn_parallel_explorers",
    label: "Spawn parallel explorers",
    description:
      "Fan out N explorer subagents in parallel, each given an independent sub-question. " +
      "Blocks until all finish, then returns {results: [{id, output, success}]}. " +
      "Use this when you need to investigate multiple independent aspects of a question at once; " +
      "for sequential or dependent questions, call bash/read tools yourself or spawn one at a time.",
    promptSnippet: "spawn_parallel_explorers: fan out explorer subagents to investigate independent sub-questions in parallel.",
    parameters: SpawnParams,
    async execute(
      _toolCallId: string,
      params: { tasks: Array<{ id: string; prompt: string }> },
    ) {
      const tasks = params.tasks.slice(0, maxParallel);
      roundIndex += 1;
      const round = roundIndex;

      const specs = tasks.map((t) => ({ agent: ctx.explorer, prompt: t.prompt }));
      const subResults = await runSubagentsParallel(specs, ctx.baseOpts);

      const results = tasks.map((t, i) => ({
        id: t.id,
        success: subResults[i].success,
        output: subResults[i].output,
        ...(subResults[i].error ? { error: subResults[i].error } : {}),
      }));
      ctx.onRoundComplete?.(round, results);

      // Return shape matches pi-coding-agent's AgentToolResult contract: a
      // plain object becomes the stringified tool result the LLM sees.
      return {
        output: JSON.stringify({ round, count: results.length, results }),
        details: { round, count: results.length },
      };
    },
  };
}

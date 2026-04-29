/**
 * Flow dispatcher — maps a flow name to its entry function.
 *
 * Invoked from agent.ts. Add new flows here + in the FLOW_NAMES export so
 * druppie's execute_coding_task_pi schema can enumerate them.
 */
import type { AgentConfig, RunResult, TaskSpec } from "../types.js";
import { runTddFlow } from "./tdd-wrapper.js";
import { runExploreFlow } from "./explore.js";

export type FlowName = "tdd" | "explore";

export const FLOW_NAMES: readonly FlowName[] = ["tdd", "explore"] as const;

export const FLOW_DESCRIPTIONS: Record<FlowName, string> = {
  tdd: "Analyst → plan → build → verify → PR. Writes code. Use for implementation tasks.",
  explore:
    "Router agent reads the repo (and/or fans out parallel explorer subagents) to answer a question. Read-only, no commits.",
};

export async function runFlow(
  flow: FlowName,
  task: TaskSpec,
  config: AgentConfig,
): Promise<RunResult> {
  switch (flow) {
    case "tdd":
      return runTddFlow(task, config);
    case "explore":
      return runExploreFlow(task, config);
    default: {
      const _exhaustive: never = flow;
      throw new Error(`Unknown flow: ${_exhaustive}`);
    }
  }
}

export { runTddFlow } from "./tdd-wrapper.js";
export { runExploreFlow } from "./explore.js";

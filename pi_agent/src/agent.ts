/**
 * Main entry point — delegates to the orchestrator.
 *
 * This is the simple API: give it a task, get a result.
 */
import { orchestrate } from "./orchestrator.js";
import type { AgentConfig, RunResult, TaskSpec } from "./types.js";

export async function runOneShotAgent(task: TaskSpec, config: AgentConfig): Promise<RunResult> {
  return orchestrate(task, config);
}

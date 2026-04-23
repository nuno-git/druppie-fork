/**
 * Main entry point — dispatches to a flow (tdd, explore, …).
 *
 * Flow is chosen by `config.flow` (set from the CLI's --flow arg or
 * environment). Defaults to `tdd` to preserve legacy behaviour.
 */
import { runFlow, type FlowName, FLOW_NAMES } from "./flows/index.js";
import type { AgentConfig, RunResult, TaskSpec } from "./types.js";

export async function runOneShotAgent(task: TaskSpec, config: AgentConfig): Promise<RunResult> {
  const raw = (config.flow ?? process.env.PI_AGENT_FLOW ?? "tdd") as FlowName;
  if (!FLOW_NAMES.includes(raw)) {
    throw new Error(`Unknown pi_agent flow "${raw}". Available: ${FLOW_NAMES.join(", ")}`);
  }
  return runFlow(raw, task, config);
}

/**
 * TDD Flow entry point.
 *
 * Delegates to the YAML-based FlowExecutor which reads .pi/flows/tdd.yaml
 * and runs phases declaratively.
 */

import type { TaskSpec, AgentConfig, RunResult } from "../types.js";
import type { Journal } from "../journal.js";
import { runTddFlowYaml } from "./tdd-yaml.js";

export async function runTddFlow(task: TaskSpec, config: AgentConfig, journal?: Journal): Promise<RunResult> {
  return runTddFlowYaml(task, config, journal);
}

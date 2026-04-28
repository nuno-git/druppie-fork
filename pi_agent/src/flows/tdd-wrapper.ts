/**
 * TDD Flow entry point with YAML flow support.
 *
 * Checks the PI_AGENT_USE_YAML_FLOW environment variable to decide
 * whether to use the new YAML-based executor or the legacy TypeScript flow.
 */

import { join } from "node:path";
import type { TaskSpec, AgentConfig } from "../types.js";
import type { Journal } from "../journal.js";
import type { RunResult } from "../types.js";
import { runTddFlowYaml } from "./tdd-yaml.js";

/**
 * Run the TDD flow using either YAML or legacy implementation.
 *
 * Set PI_AGENT_USE_YAML_FLOW=1 to use the new YAML-based executor.
 * Defaults to legacy flow for backwards compatibility.
 *
 * @param task - Task specification
 * @param config - Agent configuration
 * @param journal - Optional journal for observability (only used by YAML flow)
 * @returns Run result with summaries and deliverables
 */
export async function runTddFlow(task: TaskSpec, config: AgentConfig, journal?: Journal): Promise<RunResult> {
  const useYamlFlow = process.env.PI_AGENT_USE_YAML_FLOW === "1";

  if (useYamlFlow) {
    console.log("[flow] Using YAML-based TDD flow");
    return runTddFlowYaml(task, config, journal);
  } else {
    console.log("[flow] Using legacy TypeScript TDD flow");
    // Import legacy flow dynamically to avoid circular dependency
    const { runTddFlow: runTddFlowLegacy } = await import("./tdd.js");
    // Legacy flow doesn't accept journal parameter
    return runTddFlowLegacy(task, config);
  }
}

/**
 * Run TDD flow using the YAML-based FlowExecutor.
 *
 * This is the new entry point that uses the YAML flow definition
 * instead of the hardcoded orchestrator.
 */

import { join } from "node:path";
import type { TaskSpec, AgentConfig } from "../types.js";
import { FlowExecutor } from "../flows/executor/FlowExecutor.js";
import type { Journal } from "../journal.js";
import type { RunResult } from "../types.js";

/**
 * Run the TDD flow using the YAML-based executor.
 *
 * @param task - Task specification
 * @param config - Agent configuration
 * @param journal - Optional journal for observability
 * @returns Run result with summaries and deliverables
 */
export async function runTddFlowYaml(task: TaskSpec, config: AgentConfig, journal?: Journal): Promise<RunResult> {
  const flowPath = join(config.projectRoot || config.workDir, ".pi", "flows", "tdd.yaml");

  const executor = new FlowExecutor(journal);
  const result = await executor.execute(flowPath, task, config);

  // Convert FlowResult to RunResult for backwards compatibility
  return {
    success: result.success,
    branch: result.deliverables?.branch || "",
    commits: result.deliverables?.commits?.map((c: any) => c.sha || c || "") || [],
    testsPassed: Boolean(result.variables["testsPassed"] || result.variables["@verifier.testsPassed"]),
    buildPassed: Boolean(result.variables["buildPassed"] || result.variables["@verifier.buildPassed"]),
    summary: Object.values(result.summaries).join("\n\n"),
    errors: result.errors,
    stepResults: [],
    iterations: Number(result.variables["iteration"] || 1),
  };
}

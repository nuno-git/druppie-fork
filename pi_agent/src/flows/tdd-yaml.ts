/**
 * Run TDD flow using the YAML-based FlowExecutor.
 *
 * This is the new entry point that uses the YAML flow definition
 * instead of the hardcoded orchestrator.
 */

import { join } from "node:path";
import type { TaskSpec, AgentConfig, RunResult } from "../types.js";
import { FlowExecutor } from "../flows/executor/FlowExecutor.js";
import { Journal } from "../journal.js";

/**
 * Run the TDD flow using the YAML-based executor.
 *
 * @param task - Task specification
 * @param config - Agent configuration
 * @param _journal - Unused, kept for backward compatibility
 * @returns Run result with summaries and deliverables
 */
export async function runTddFlowYaml(task: TaskSpec, config: AgentConfig, _journal?: Journal): Promise<RunResult> {
  const flowPath = join(config.projectRoot || config.workDir, ".pi", "flows", "tdd.yaml");

  // Create journal for event tracking + summary output
  const journal = new Journal(config.workDir, task);

  const executor = new FlowExecutor(journal);
  const result = await executor.execute(flowPath, task, config);

  // Close journal — writes summary.json + posts to ingest URL
  await journal.close(result.success);

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

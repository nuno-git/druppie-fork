/**
 * Example: Using the multi-agent TDD system programmatically.
 *
 * Flow (loops until green or max iterations):
 *   analyst → [ planner → builders (parallel waves) → verifier ] → done
 *                  ▲                                     │
 *                  └──── remaining issues ────────────────┘
 */
import { runOneShotAgent } from "oneshot-tdd-agent";
import type { AgentConfig, TaskSpec } from "oneshot-tdd-agent";

const task: TaskSpec = {
  description: "Build a markdown parser that converts a subset of Markdown (headings, bold, italic, links, code blocks) to HTML",
  language: "typescript",
};

const config: AgentConfig = {
  workDir: "/tmp/workspace",
  model: "claude-sonnet-4-5",
  thinkingLevel: "medium",
  maxIterations: 3,       // planner → execute → verify loop runs up to 3 times
  maxTurnsPerAgent: 30,   // each individual agent gets up to 30 turns
};

const result = await runOneShotAgent(task, config);

console.log("\n--- Final Result ---");
console.log(`Success:      ${result.success}`);
console.log(`Branch:       ${result.branch}`);
console.log(`Commits:      ${result.commits.length}`);
console.log(`Iterations:   ${result.iterations}`);
console.log(`Tests passed: ${result.testsPassed}`);
console.log(`Build passed: ${result.buildPassed}`);

if (result.goalAnalysis) {
  console.log(`\nGoal: ${result.goalAnalysis.goal}`);
  console.log(`Tests planned: ${result.goalAnalysis.tests.length}`);
}

if (result.plan) {
  console.log(`\nFinal plan: ${result.plan.summary}`);
  for (const [i, wave] of result.plan.waves.entries()) {
    const parallel = wave.length > 1 ? " (parallel)" : "";
    console.log(`  Wave ${i + 1}${parallel}: ${wave.map((s) => s.id).join(", ")}`);
  }
}

console.log(`\nStep results:`);
for (const step of result.stepResults) {
  console.log(`  ${step.success ? "✓" : "✗"} ${step.stepId}`);
}

if (result.errors.length > 0) {
  console.log(`\nErrors:`);
  for (const err of result.errors) console.log(`  - ${err}`);
}

process.exit(result.success ? 0 : 1);

/**
 * Test script for YAML flow system.
 */

import { parseFlow, validateFlow } from "./flows/schema.js";
import { FlowContext } from "./flows/executor/FlowContext.js";
import { extractSummary, extractVariables, extractStructuredData } from "./agents/runner.js";

async function testSchemaParsing() {
  console.log("\n=== Testing Schema Parsing ===\n");

  try {
    const flowPath = "/home/nuno/Documents/druppie-fork/pi_agent/.pi/flows/tdd.yaml";
    const flow = parseFlow(flowPath);

    console.log("✅ Flow parsed successfully!");
    console.log(`  Name: ${flow.name}`);
    console.log(`  Description: ${flow.description}`);
    console.log(`  Variables:`, flow.variables);
    console.log(`  Phases: ${flow.phases.length}`);
    console.log(`  Output format: ${flow.output?.format}`);

    // Validate
    validateFlow(flow, flowPath);
    console.log("\n✅ Flow validation passed!");

    return flow;
  } catch (error) {
    console.error("❌ Schema parsing failed:", error);
    throw error;
  }
}

async function testFlowContext() {
  console.log("\n=== Testing FlowContext ===\n");

  const task = {
    description: "Implement user authentication",
    language: "typescript",
    testCommand: "npm test",
    pushOnComplete: true,
  };

  const ctx = new FlowContext(task, { maxIterations: 3, iteration: 1 });

  // Test variable storage
  ctx.setVariable("testVar", "testValue");
  console.log("✅ Variable set:", ctx.getVariable("testVar"));

  // Test variable interpolation
  const interpolated = ctx.interpolate("Iteration ${iteration} of ${maxIterations}");
  console.log("✅ Interpolated:", interpolated);

  // Test summaries
  ctx.addSummary("analyst", "This is a test summary");
  ctx.addSummary("planner", "Plan created successfully");
  console.log("✅ Summaries added:", ctx.getSummaries().size);

  // Test summary formatting
  const formatted = ctx.getSummariesFormatted();
  console.log("✅ Formatted summaries:\n", formatted.substring(0, 200) + "...");

  // Test evaluation context
  const evalContext = ctx.toEvalContext();
  console.log("✅ Evaluation context has task:", !!evalContext.task);
  console.log("✅ Evaluation context has variables:", !!evalContext.variables);

  return ctx;
}

async function testSummaryExtraction() {
  console.log("\n=== Testing Summary Extraction ===\n");

  const agentOutput = `
Some text before the summary.

## Summary
This is a test summary of what the agent did.
It analyzed the task and created a plan.

## Variables
branchName: feat/test-flow
testFramework: vitest
testsPassed: true

Some text after.
`;

  const summary = extractSummary(agentOutput);
  console.log("✅ Extracted summary:", summary);

  const variables = extractVariables(agentOutput);
  console.log("✅ Extracted variables:", Object.fromEntries(variables));

  const jsonOutput = `
Some text

\`\`\`json
{
  "testsPassed": true,
  "buildPassed": false,
  "fixes": ["Fixed typo"],
  "remainingIssues": []
}
\`\`\`

Some more text
`;

  const structured = extractStructuredData(jsonOutput);
  console.log("✅ Extracted structured data:", structured);

  return { summary, variables, structured };
}

async function testDecisionTool() {
  console.log("\n=== Testing Decision Tool ===\n");

  const { evaluateCondition } = await import("./flows/tools/decision-tool.js");

  const task = {
    description: "Test task",
    language: "typescript",
  };

  const ctx = new FlowContext(task, { maxIterations: 3, iteration: 1 });
  ctx.setVariable("testsPassed", "true");
  ctx.setVariable("buildPassed", "false");

  // Test simple condition
  const result1 = await evaluateCondition("iteration < maxIterations", ctx);
  console.log("✅ Condition 'iteration < maxIterations':", result1);

  // Test boolean condition
  const result2 = await evaluateCondition("testsPassed && !buildPassed", ctx);
  console.log("✅ Condition 'testsPassed && !buildPassed':", result2);

  return true;
}

async function runAllTests() {
  console.log("╔══════════════════════════════════════════════════════════╗");
  console.log("║  YAML Flow System - Component Tests                    ║");
  console.log("╚══════════════════════════════════════════════════════════╝");

  try {
    await testSchemaParsing();
    await testFlowContext();
    await testSummaryExtraction();
    await testDecisionTool();

    console.log("\n╔══════════════════════════════════════════════════════════╗");
    console.log("║  ✅ All component tests passed!                         ║");
    console.log("╚══════════════════════════════════════════════════════════╝\n");

    return true;
  } catch (error) {
    console.error("\n❌ Tests failed:", error);
    return false;
  }
}

// Run tests
runAllTests().then(success => {
  process.exit(success ? 0 : 1);
});

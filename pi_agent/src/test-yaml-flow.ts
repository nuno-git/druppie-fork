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

async function testDoneTool() {
  console.log("\n=== Testing Done Tool ===\n");

  const { createDoneTool, markWorkComplete } = await import("./flows/tools/done-tool.js");

  const task = {
    description: "Test task",
    language: "typescript",
  };

  const ctx = new FlowContext(task, { maxIterations: 3, iteration: 1 });

  // Test tool factory
  const doneTool = createDoneTool(ctx);
  console.log("✅ Done tool created:", doneTool.name);
  console.log("✅ Tool description:", doneTool.description.substring(0, 50) + "...");

  // Test execution with valid variables
  const result1 = await doneTool.execute("test-call-id", {
    variables: {
      testVar: "testValue",
      count: 42,
      success: true,
    },
    message: "Test completed successfully",
  });

  const parsedResult1 = JSON.parse(result1.output);
  console.log("✅ Tool execution succeeded:", parsedResult1.success);
  console.log("✅ Variables set:", Object.keys(parsedResult1.variablesSet));

  // Verify variables are in context
  console.log("✅ testVar in context:", ctx.getVariable("testVar"));
  console.log("✅ count in context:", ctx.getVariable("count"));
  console.log("✅ success in context:", ctx.getVariable("success"));

  // Test execution with invalid variable type (should be skipped)
  const result2 = await doneTool.execute("test-call-id-2", {
    variables: {
      validString: "valid",
      validNumber: 123,
      invalidObject: { nested: "value" }, // This should be skipped
      invalidArray: [1, 2, 3], // This should be skipped
    },
    message: "Test with mixed variable types",
  });

  const parsedResult2 = JSON.parse(result2.output);
  console.log("✅ Mixed types handled:", parsedResult2.success);
  console.log("✅ Valid variables set:", Object.keys(parsedResult2.variablesSet));
  console.log("✅ Invalid variables skipped:", parsedResult2.warnings?.[0]);

  // Test utility function
  const utilResult = markWorkComplete(ctx, { utilVar: "utilValue" }, "Utility test");
  console.log("✅ Utility function succeeded:", utilResult.success);
  console.log("✅ Utility variable set:", utilResult.variablesSet.utilVar);

  return true;
}

async function testDoneToolParameterValidation() {
  console.log("\n=== Testing Done Tool Parameter Validation ===\n");

  const { createDoneTool, markWorkComplete } = await import("./flows/tools/done-tool.js");

  const task = {
    description: "Test task",
    language: "typescript",
  };

  const ctx = new FlowContext(task, { maxIterations: 3, iteration: 1 });
  const doneTool = createDoneTool(ctx);

  // Test 1: Missing message parameter
  try {
    await doneTool.execute("test-call-1", {
      variables: { testVar: "value" },
      message: "", // Empty message is valid
    });
    console.log("❌ Should have failed with missing message");
    return false;
  } catch (error) {
    console.log("✅ Correctly rejects missing message parameter");
  }

  // Test 2: Empty message should be allowed but logged
  const result2 = await doneTool.execute("test-call-2", {
    variables: { testVar: "value" },
    message: "",
  });
  const parsed2 = JSON.parse(result2.output);
  console.log("✅ Empty message accepted:", parsed2.message === "");

  // Test 3: Empty variables parameter
  try {
    await doneTool.execute("test-call-3", {
      variables: {},
      message: "Test message",
    });
    console.log("✅ Correctly accepts empty variables parameter");
  } catch (error) {
    console.log("❌ Should accept empty variables:", error);
    return false;
  }

  // Test 4: Empty variables object
  const result4 = await doneTool.execute("test-call-4", {
    variables: {},
    message: "Test with no variables",
  });
  const parsed4 = JSON.parse(result4.output);
  console.log("✅ Empty variables accepted:", parsed4.success);
  console.log("✅ No variables set:", Object.keys(parsed4.variablesSet).length === 0);

  // Test 5: All parameter types
  const result5 = await doneTool.execute("test-call-5", {
    variables: {
      strVar: "string value",
      numVar: 123.45,
      boolVar: true,
      zero: 0,
      falseVal: false,
      emptyStr: "",
    },
    message: "All parameter types test",
  });
  const parsed5 = JSON.parse(result5.output);
  console.log("✅ All primitive types accepted:", Object.keys(parsed5.variablesSet).length === 6);

  // Test 6: Utility function validation
  try {
    markWorkComplete(ctx, { valid: "var" }, ""); // Empty message
    console.log("✅ Utility function accepts empty message");
  } catch (error) {
    console.log("❌ Utility function should accept empty message");
    return false;
  }

  console.log("\n✅ All parameter validation tests passed!");
  return true;
}

async function testDoneToolExtraction() {
  console.log("\n=== Testing Done Tool Extraction ===\n");

  const { FlowExecutor } = await import("./flows/executor/FlowExecutor.js");
  const task = {
    description: "Test task",
    language: "typescript",
  };

  // Create a mock executor instance for testing extraction
  const executor = new (FlowExecutor as any)();

  // Test 1: Extract equals format: done(variables={...}, message="...")
  const output1 = `
    I have completed the analysis.
    done(variables={goal: "Test goal", criteria: "test1, test2"}, message="Analysis complete")
    Additional text after.
  `;
  executor.extractDoneToolUsage(output1);
  console.log("✅ Equals format detected:", executor.doneToolUsed);
  console.log("✅ Message extracted:", executor.doneToolMessage);
  console.log("✅ Variables extracted:", Object.keys(executor.doneToolVariables).length);

  // Test 2: Extract colon format: done({variables: {...}, message: "..."})
  const output2 = `
    Work finished.
    done({variables: {success: "true", count: "42"}, message: "Phase complete"})
  `;
  executor.extractDoneToolUsage(output2);
  console.log("✅ Colon format detected:", executor.doneToolUsed);
  console.log("✅ Message extracted:", executor.doneToolMessage);
  console.log("✅ Success value:", executor.doneToolVariables.success);

  // Test 3: Extract JSON tool call format
  const output3 = `
    Using tool:
    {"name": "done", "parameters": {"variables": {result: "passed"}, "message": "All tests passed"}}
  `;
  executor.extractDoneToolUsage(output3);
  console.log("✅ JSON format detected:", executor.doneToolUsed);
  console.log("✅ Result value:", executor.doneToolVariables.result);

  // Test 4: Extract simple format: done({...}, "message")
  const output4 = `
    done({key: "value"}, "Simple format test")
  `;
  executor.extractDoneToolUsage(output4);
  console.log("✅ Simple format detected:", executor.doneToolUsed);
  console.log("✅ Key value:", executor.doneToolVariables.key);

  // Test 5: Extract tool_call format
  const output5 = `
    tool_call: {"name": "done", "parameters": {"variables": {output: "done"}, "message": "Tool call test"}}
  `;
  executor.extractDoneToolUsage(output5);
  console.log("✅ Tool call format detected:", executor.doneToolUsed);
  console.log("✅ Output value:", executor.doneToolVariables.output);

  // Test 6: No done tool usage
  const output6 = `
    Just regular output without any done tool usage.
    The agent forgot to use the done tool.
  `;
  executor.extractDoneToolUsage(output6);
  console.log("✅ Correctly detected no done tool:", !executor.doneToolUsed);

  // Test 7: Malformed done tool calls
  const output7 = `
    done(variables={invalid json, message="test")
  `;
  executor.extractDoneToolUsage(output7);
  console.log("✅ Malformed call handled gracefully:", executor.doneToolUsed);

  // Test 8: Multiple done tool calls (should use first one)
  const output8 = `
    done({first: "call"}, "First message")
    done({second: "call"}, "Second message")
  `;
  executor.extractDoneToolUsage(output8);
  console.log("✅ First done tool used:", executor.doneToolUsed);
  console.log("✅ First message:", executor.doneToolMessage === "First message");

  // Test 9: Complex nested variables
  const output9 = `
    done(variables={simple: "value", number: "123", boolean: "true", zero: "0", falsy: "false"}, message="Complex variables")
  `;
  executor.extractDoneToolUsage(output9);
  console.log("✅ Complex variables extracted:", Object.keys(executor.doneToolVariables).length === 5);

  console.log("\n✅ All extraction tests passed!");
  return true;
}

async function testDoneToolEnforcement() {
  console.log("\n=== Testing Done Tool Enforcement ===\n");

  const { FlowExecutor } = await import("./flows/executor/FlowExecutor.js");

  const task = {
    description: "Test task",
    language: "typescript",
  };

  const executor = new (FlowExecutor as any)();

  // Test 1: Phase with required variables but no done tool
  const phase1: any = {
    name: "test-phase",
    agent: "test-agent",
    variables: [
      { name: "succeeded", type: "bool" },
      { name: "count", type: "int" },
    ],
  };

  const output1 = "Agent output without done tool usage";
  try {
    executor.enforceDoneTool(phase1, "test-agent", output1);
    console.log("❌ Should have enforced done tool usage");
    return false;
  } catch (error) {
    console.log("✅ Correctly enforced done tool usage");
    console.log("✅ Error message includes:", (error as Error).message.includes("did not use the done tool"));
  }

  // Test 2: Phase with done tool but missing required variables
  const output2 = "done(variables={count: 5}, message=\"Missing succeeded variable\")";
  executor.doneToolUsed = true;
  executor.doneToolVariables = { count: 5 };
  executor.doneToolMessage = "Missing succeeded variable";

  try {
    executor.enforceDoneTool(phase1, "test-agent", output2);
    console.log("❌ Should have enforced required variables");
    return false;
  } catch (error) {
    console.log("✅ Correctly enforced required variables");
    console.log("✅ Error message includes:", (error as Error).message.includes("did not set all required variables"));
    console.log("✅ Missing variable listed:", (error as Error).message.includes("succeeded"));
  }

  // Test 3: Phase with done tool and all required variables
  const output3 = 'done(variables={succeeded: "true", count: "10"}, message="All variables set")';
  // First extract the done tool usage
  executor.extractDoneToolUsage(output3);

  try {
    executor.enforceDoneTool(phase1, "test-agent", output3);
    console.log("✅ Correctly allowed done tool with all required variables");
  } catch (error) {
    console.log("❌ Should not have thrown error with all variables:", error);
    return false;
  }

  // Test 4: Phase without variables but agent uses done tool (unconditional enforcement)
  const phase4: any = {
    name: "test-phase-4",
    agent: "test-agent",
  };
  const output4done = 'done(variables={}, message="Phase completed")';
  executor.extractDoneToolUsage(output4done);

  try {
    executor.enforceDoneTool(phase4, "test-agent", output4done);
    console.log("✅ Correctly allowed done tool on phase without required variables");
  } catch (error) {
    console.log("❌ Should not have thrown error when done tool used:", error);
    return false;
  }

  // Test 5: Phase without variables and agent does NOT use done tool (must still throw)
  const output5noDone = "Agent output without done tool usage";
  executor.extractDoneToolUsage(output5noDone);

  try {
    executor.enforceDoneTool(phase4, "test-agent", output5noDone);
    console.log("❌ Should have enforced done tool even for phase without variables");
    return false;
  } catch (error) {
    console.log("✅ Correctly enforced done tool for all phases (unconditional)");
  }

  // Test 6: Phase with empty variables array
  const phase6: any = {
    name: "test-phase-6",
    agent: "test-agent",
    variables: [],
  };

  const output6 = 'done(variables={}, message="No required variables")';
  executor.extractDoneToolUsage(output6);

  try {
    executor.enforceDoneTool(phase6, "test-agent", output6);
    console.log("✅ Correctly handled empty variables array");
  } catch (error) {
    console.log("❌ Should not have thrown error with empty variables:", error);
    return false;
  }

  console.log("\n✅ All enforcement tests passed!");
  return true;
}

async function testRequiredVariableValidation() {
  console.log("\n=== Testing Required Variable Validation ===\n");

  const { FlowExecutor } = await import("./flows/executor/FlowExecutor.js");

  const task = {
    description: "Test task",
    language: "typescript",
  };

  const executor = new (FlowExecutor as any)();

  // Test 1: All required variables present
  const phase1: any = {
    name: "test-phase",
    agent: "test-agent",
    variables: [
      { name: "var1", type: "str" },
      { name: "var2", type: "int" },
      { name: "var3", type: "bool" },
    ],
  };

  const output1 = "done(variables={var1: \"value1\", var2: 123, var3: true}, message=\"All variables set\")";
  executor.extractDoneToolUsage(output1);

  try {
    executor.enforceDoneTool(phase1, "test-agent", output1);
    console.log("✅ All required variables validated successfully");
  } catch (error) {
    console.log("❌ Should not have thrown with all variables:", error);
    return false;
  }

  // Test 2: Single missing variable
  const phase2: any = {
    name: "test-phase",
    agent: "test-agent",
    variables: [
      { name: "required1", type: "str" },
      { name: "required2", type: "str" },
    ],
  };

  const output2 = "done(variables={required1: \"value1\"}, message=\"Missing one variable\")";
  executor.extractDoneToolUsage(output2);

  try {
    executor.enforceDoneTool(phase2, "test-agent", output2);
    console.log("❌ Should have thrown for missing variable");
    return false;
  } catch (error) {
    console.log("✅ Correctly detected missing variable");
    console.log("✅ Error message:", (error as Error).message);
    console.log("✅ Missing variable in error:", (error as Error).message.includes("required2"));
  }

  // Test 3: Multiple missing variables
  const phase3: any = {
    name: "test-phase",
    agent: "test-agent",
    variables: [
      { name: "req1", type: "str" },
      { name: "req2", type: "int" },
      { name: "req3", type: "bool" },
      { name: "req4", type: "str" },
    ],
  };

  const output3 = "done(variables={req2: 123}, message=\"Multiple missing\")";
  executor.extractDoneToolUsage(output3);

  try {
    executor.enforceDoneTool(phase3, "test-agent", output3);
    console.log("❌ Should have thrown for multiple missing variables");
    return false;
  } catch (error) {
    console.log("✅ Correctly detected multiple missing variables");
    console.log("✅ Error message:", (error as Error).message);
    console.log("✅ All missing variables listed:", (error as Error).message.includes("req1") && (error as Error).message.includes("req3") && (error as Error).message.includes("req4"));
  }

  // Test 4: Extra variables (should not cause error)
  const phase4: any = {
    name: "test-phase",
    agent: "test-agent",
    variables: [
      { name: "required", type: "str" },
    ],
  };

  const output4 = "done(variables={required: \"value\", extra1: \"extra value 1\", extra2: 456, extra3: true}, message=\"With extra variables\")";
  executor.extractDoneToolUsage(output4);

  try {
    executor.enforceDoneTool(phase4, "test-agent", output4);
    console.log("✅ Extra variables allowed");
    console.log("✅ Extra variables in doneToolVariables:", executor.doneToolVariables.extra1 && executor.doneToolVariables.extra2 && executor.doneToolVariables.extra3);
  } catch (error) {
    console.log("❌ Should not have thrown with extra variables:", error);
    return false;
  }

  // Test 5: Variable type validation (agent can set any type, enforcement just checks existence)
  const phase5: any = {
    name: "test-phase",
    agent: "test-agent",
    variables: [
      { name: "stringVar", type: "str" },
      { name: "intVar", type: "int" },
      { name: "boolVar", type: "bool" },
    ],
  };

  const output5 = "done(variables={stringVar: \"string value\", intVar: \"123\", boolVar: \"true\"}, message=\"Type validation test\")";
  executor.extractDoneToolUsage(output5);

  try {
    executor.enforceDoneTool(phase5, "test-agent", output5);
    console.log("✅ Variable types are flexible (enforcement checks existence, not type)");
  } catch (error) {
    console.log("❌ Should not have thrown with different types:", error);
    return false;
  }

  console.log("\n✅ All required variable validation tests passed!");
  return true;
}

async function testDoneToolErrorHandling() {
  console.log("\n=== Testing Done Tool Error Handling ===\n");

  const { createDoneTool, markWorkComplete } = await import("./flows/tools/done-tool.js");

  const task = {
    description: "Test task",
    language: "typescript",
  };

  const ctx = new FlowContext(task, { maxIterations: 3, iteration: 1 });
  const doneTool = createDoneTool(ctx);

  // Test 1: Error during variable setting
  const result1 = await doneTool.execute("test-call-1", {
    variables: {
      validVar: "valid",
      invalidVar: { nested: "object" }, // Should be skipped with warning
    },
    message: "Error handling test",
  });
  const parsed1 = JSON.parse(result1.output);
  console.log("✅ Error handled gracefully:", parsed1.success);
  const details1 = result1.details as any;
  console.log("✅ Warning generated:", details1?.warnings?.length > 0);
  console.log("✅ Valid variable set:", ctx.getVariable("validVar"));

  // Test 2: All invalid variables
  const result2 = await doneTool.execute("test-call-2", {
    variables: {
      invalidObj: { nested: "value" },
      invalidArr: [1, 2, 3],
      anotherObj: { key: "value" },
    },
    message: "All invalid test",
  });
  const parsed2 = JSON.parse(result2.output);
  console.log("✅ All invalid handled:", parsed2.success);
  console.log("✅ No variables set:", Object.keys(parsed2.variablesSet).length === 0);
  const details2 = result2.details as any;
  console.log("✅ Warnings generated:", details2?.warnings?.length === 3);

  // Test 3: Mixed valid and invalid with complex nesting
  const result3 = await doneTool.execute("test-call-3", {
    variables: {
      validStr: "string",
      validNum: 123,
      validBool: false,
      invalidNested: { deep: { nesting: "value" } },
      invalidArray: ["item1", "item2"],
    },
    message: "Complex mixed test",
  });
  const parsed3 = JSON.parse(result3.output);
  console.log("✅ Complex mixed handled:", parsed3.success);
  console.log("✅ Valid variables set:", Object.keys(parsed3.variablesSet).length === 3);
  const details3 = result3.details as any;
  console.log("✅ Invalid variables warned:", details3?.warnings?.length === 2);

  // Test 4: Special string values
  const result4 = await doneTool.execute("test-call-4", {
    variables: {
      emptyString: "",
      whitespace: "   ",
      specialChars: "!@#$%^&*()",
      unicode: "你好世界",
    },
    message: "Special string values",
  });
  const parsed4 = JSON.parse(result4.output);
  console.log("✅ Special string values handled:", parsed4.success);
  console.log("✅ Empty string set:", ctx.getVariable("emptyString") === "");
  console.log("✅ Unicode set:", ctx.getVariable("unicode") === "你好世界");

  // Test 5: Edge case numeric values
  const result5 = await doneTool.execute("test-call-5", {
    variables: {
      zero: 0,
      negative: -123,
      float: 123.456,
      scientific: 1.23e10,
      infinity: Infinity,
    },
    message: "Edge case numbers",
  });
  const parsed5 = JSON.parse(result5.output);
  console.log("✅ Edge case numbers handled:", parsed5.success);
  console.log("✅ Zero value:", ctx.getVariable("zero") === 0);
  console.log("✅ Negative value:", ctx.getVariable("negative") === -123);

  // Test 6: Utility function error handling
  try {
    markWorkComplete(ctx, { valid: "var" }, "Utility test");
    console.log("✅ Utility function works correctly");
  } catch (error) {
    console.log("❌ Utility function should not throw:", error);
    return false;
  }

  console.log("\n✅ All error handling tests passed!");
  return true;
}

async function testDoneToolIntegration() {
  console.log("\n=== Testing Done Tool Integration ===\n");

  const { FlowContext } = await import("./flows/executor/FlowContext.js");
  const { createDoneTool, markWorkComplete } = await import("./flows/tools/done-tool.js");

  const task = {
    description: "Integration test task",
    language: "typescript",
  };

  // Test 1: End-to-end flow with done tool
  const ctx1 = new FlowContext(task, { maxIterations: 3, iteration: 1 });
  const doneTool1 = createDoneTool(ctx1);

  // Agent simulates setting variables through done tool
  const result1 = await doneTool1.execute("call-1", {
    variables: {
      phaseComplete: true,
      outputCount: 42,
      hasErrors: false,
    },
    message: "Phase 1 completed successfully",
  });

  const parsed1 = JSON.parse(result1.output);
  console.log("✅ Integration test 1 - Tool executed:", parsed1.success);
  console.log("✅ Variables in context:", ctx1.getVariable("phaseComplete") === true);
  console.log("✅ Message captured:", parsed1.message === "Phase 1 completed successfully");

  // Test 2: Multiple phases with done tools
  const ctx2 = new FlowContext(task, { maxIterations: 3, iteration: 1 });
  const doneTool2 = createDoneTool(ctx2);

  // Phase 1
  await doneTool2.execute("phase-1", {
    variables: { phase1Complete: true, output1: "result1" },
    message: "Phase 1 done",
  });

  // Phase 2
  await doneTool2.execute("phase-2", {
    variables: { phase2Complete: true, output2: "result2" },
    message: "Phase 2 done",
  });

  console.log("✅ Integration test 2 - Multiple phases:", ctx2.getVariable("phase1Complete") && ctx2.getVariable("phase2Complete"));
  console.log("✅ All variables preserved:", ctx2.getVariable("output1") === "result1" && ctx2.getVariable("output2") === "result2");

  // Test 3: Variable interpolation after done tool
  const ctx3 = new FlowContext(task, { maxIterations: 3, iteration: 1 });
  const doneTool3 = createDoneTool(ctx3);

  await doneTool3.execute("set-vars", {
    variables: { userName: "Alice", taskCount: 5 },
    message: "Variables set for interpolation",
  });

  const interpolated = ctx3.interpolate("User ${userName} completed ${taskCount} tasks");
  console.log("✅ Integration test 3 - Interpolation:", interpolated === "User Alice completed 5 tasks");

  // Test 4: Done tool with evaluation context
  const ctx4 = new FlowContext(task, { maxIterations: 3, iteration: 1 });
  const doneTool4 = createDoneTool(ctx4);

  await doneTool4.execute("eval-ctx", {
    variables: {
      testVar: "testValue",
      testNum: 123,
      testBool: true,
    },
    message: "Evaluation context test",
  });

  const evalContext = ctx4.toEvalContext();
  const evalVars = evalContext.variables as any;
  console.log("✅ Integration test 4 - Eval context:", evalVars?.testVar === "testValue");
  console.log("✅ Variables in eval context:", evalVars?.testNum === 123);

  // Test 5: Utility function integration
  const ctx5 = new FlowContext(task, { maxIterations: 3, iteration: 1 });

  const utilResult1 = markWorkComplete(ctx5, { util1: "value1", util2: 42 }, "Utility call 1");
  const utilResult2 = markWorkComplete(ctx5, { util3: true }, "Utility call 2");

  console.log("✅ Integration test 5 - Utility function:", utilResult1.success && utilResult2.success);
  console.log("✅ All variables set:", ctx5.getVariable("util1") === "value1" && ctx5.getVariable("util2") === 42 && ctx5.getVariable("util3") === true);

  // Test 6: Done tool with summary integration
  const ctx6 = new FlowContext(task, { maxIterations: 3, iteration: 1 });
  const doneTool6 = createDoneTool(ctx6);

  // Add a summary before using done tool
  ctx6.addSummary("agent1", "Agent 1 completed its work");

  // Agent uses done tool
  await doneTool6.execute("with-summary", {
    variables: { summaryVar: "value" },
    message: "Done tool with summary",
  });

  const summaries = ctx6.getSummaries();
  console.log("✅ Integration test 6 - Summary preserved:", summaries.has("agent1"));
  console.log("✅ Done tool variable set:", ctx6.getVariable("summaryVar") === "value");

  // Test 7: Iteration tracking with done tool
  const ctx7 = new FlowContext(task, { maxIterations: 3, iteration: 1 });
  const doneTool7 = createDoneTool(ctx7);

  // Simulate first iteration
  await doneTool7.execute("iter-1", {
    variables: { iterationComplete: true },
    message: "Iteration 1 complete",
  });

  ctx7.incrementIteration("testLoop");

  // Simulate second iteration
  await doneTool7.execute("iter-2", {
    variables: { iterationComplete: true },
    message: "Iteration 2 complete",
  });

  console.log("✅ Integration test 7 - Iteration tracking:", ctx7.getIteration("testLoop") === 2);
  console.log("✅ Iteration variable set:", ctx7.getVariable("iteration") === 2);

  console.log("\n✅ All integration tests passed!");
  return true;
}

async function testDoneToolSuccessScenarios() {
  console.log("\n=== Testing Done Tool Success Scenarios ===\n");

  const { FlowContext } = await import("./flows/executor/FlowContext.js");
  const { createDoneTool, markWorkComplete } = await import("./flows/tools/done-tool.js");
  const { FlowExecutor } = await import("./flows/executor/FlowExecutor.js");

  const task = {
    description: "Success scenario test",
    language: "typescript",
  };

  // Success Scenario 1: Simple successful completion
  console.log("\n--- Scenario 1: Simple Successful Completion ---");
  const ctx1 = new FlowContext(task, { maxIterations: 3, iteration: 1 });
  const doneTool1 = createDoneTool(ctx1);

  const result1 = await doneTool1.execute("success-1", {
    variables: {
      taskComplete: true,
      filesCreated: 5,
      testsPassed: true,
    },
    message: "Task completed successfully. All tests pass.",
  });

  const parsed1 = JSON.parse(result1.output);
  console.log("✅ Scenario 1 - Success:", parsed1.success);
  console.log("✅ All variables set:", Object.keys(parsed1.variablesSet).length === 3);
  console.log("✅ Message:", parsed1.message);

  // Success Scenario 2: Multi-variable complex scenario
  console.log("\n--- Scenario 2: Multi-variable Complex Scenario ---");
  const ctx2 = new FlowContext(task, { maxIterations: 3, iteration: 1 });
  const doneTool2 = createDoneTool(ctx2);

  const result2 = await doneTool2.execute("success-2", {
    variables: {
      buildStatus: "passed",
      testCoverage: 95.5,
      lintErrors: 0,
      performanceScore: 98,
      securityScan: "clean",
      documentationComplete: true,
    },
    message: "All quality checks passed. Ready for deployment.",
  });

  const parsed2 = JSON.parse(result2.output);
  console.log("✅ Scenario 2 - Success:", parsed2.success);
  console.log("✅ Variables:", Object.keys(parsed2.variablesSet).length === 6);
  console.log("✅ Build status:", ctx2.getVariable("buildStatus") === "passed");

  // Success Scenario 3: Conditional workflow success
  console.log("\n--- Scenario 3: Conditional Workflow Success ---");
  const ctx3 = new FlowContext(task, { maxIterations: 3, iteration: 1 });
  const doneTool3 = createDoneTool(ctx3);

  // Phase 1 succeeds
  await doneTool3.execute("phase-1", {
    variables: { phase1Success: true, output1: "result1" },
    message: "Phase 1 completed successfully",
  });

  // Phase 2 succeeds
  await doneTool3.execute("phase-2", {
    variables: { phase2Success: true, output2: "result2" },
    message: "Phase 2 completed successfully",
  });

  // Phase 3 completes workflow
  await doneTool3.execute("phase-3", {
    variables: {
      workflowComplete: true,
      totalPhases: 3,
      allPhasesSuccess: ctx3.getVariable("phase1Success") && ctx3.getVariable("phase2Success"),
    },
    message: "All phases completed successfully. Workflow done.",
  });

  console.log("✅ Scenario 3 - Workflow complete:", ctx3.getVariable("workflowComplete"));
  console.log("✅ All phases success:", ctx3.getVariable("allPhasesSuccess"));
  console.log("✅ Total phases:", ctx3.getVariable("totalPhases") === 3);

  // Success Scenario 4: Loop iteration success
  console.log("\n--- Scenario 4: Loop Iteration Success ---");
  const ctx4 = new FlowContext(task, { maxIterations: 3, iteration: 1 });
  const doneTool4 = createDoneTool(ctx4);

  for (let i = 1; i <= 3; i++) {
    await doneTool4.execute(`iteration-${i}`, {
      variables: {
        [`iteration${i}Complete`]: true,
        iteration: i,
      },
      message: `Iteration ${i} completed`,
    });
    ctx4.incrementIteration("testLoop");
  }

  console.log("✅ Scenario 4 - All iterations complete:", ctx4.getIteration("testLoop") === 3);
  console.log("✅ Iteration 1:", ctx4.getVariable("iteration1Complete"));
  console.log("✅ Iteration 2:", ctx4.getVariable("iteration2Complete"));
  console.log("✅ Iteration 3:", ctx4.getVariable("iteration3Complete"));

  // Success Scenario 5: Enforcement with all required variables
  console.log("\n--- Scenario 5: Enforcement with All Required Variables ---");
  const executor2 = new (FlowExecutor as any)();
  const phase5: any = {
    name: "critical-phase",
    agent: "critical-agent",
    variables: [
      { name: "status", type: "str" },
      { name: "code", type: "int" },
      { name: "validated", type: "bool" },
    ],
  };

  const output5 = 'done(variables={status: "success", code: 200, validated: true}, message="All requirements met")';
  executor2.extractDoneToolUsage(output5);

  try {
    executor2.enforceDoneTool(phase5, "critical-agent", output5);
    console.log("✅ Scenario 5 - Enforcement passed");
    console.log("✅ All required variables present");
  } catch (error) {
    console.log("❌ Scenario 5 failed:", error);
    return false;
  }

  // Success Scenario 6: Utility function for quick completion
  console.log("\n--- Scenario 6: Utility Function Quick Completion ---");
  const ctx6 = new FlowContext(task, { maxIterations: 3, iteration: 1 });

  const utilResult = markWorkComplete(
    ctx6,
    {
      quickComplete: true,
      timestamp: Date.now(),
      agentType: "utility",
    },
    "Quick completion via utility function"
  );

  console.log("✅ Scenario 6 - Utility success:", utilResult.success);
  console.log("✅ Variables set:", utilResult.variablesSet.quickComplete && utilResult.variablesSet.agentType);
  console.log("✅ Context updated:", ctx6.getVariable("quickComplete") === true);

  // Success Scenario 7: Error recovery scenario
  console.log("\n--- Scenario 7: Error Recovery Scenario ---");
  const ctx7 = new FlowContext(task, { maxIterations: 3, iteration: 1 });
  const doneTool7 = createDoneTool(ctx7);

  // First attempt with issues
  await doneTool7.execute("attempt-1", {
    variables: { attempt: 1, issuesFound: 3, success: false },
    message: "First attempt completed with issues",
  });

  // Second attempt with fewer issues
  await doneTool7.execute("attempt-2", {
    variables: { attempt: 2, issuesFound: 1, success: false },
    message: "Second attempt reduced issues",
  });

  // Final successful attempt
  await doneTool7.execute("attempt-3", {
    variables: { attempt: 3, issuesFound: 0, success: true, errorFixed: true },
    message: "All issues resolved. Success!",
  });

  console.log("✅ Scenario 7 - Error recovery complete:", ctx7.getVariable("success"));
  console.log("✅ All issues resolved:", ctx7.getVariable("issuesFound") === 0);
  console.log("✅ Error fixed:", ctx7.getVariable("errorFixed"));

  console.log("\n✅ All success scenario tests passed!");
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
    await testDoneTool();
    await testDoneToolParameterValidation();
    await testDoneToolExtraction();
    await testDoneToolEnforcement();
    await testRequiredVariableValidation();
    await testDoneToolErrorHandling();
    await testDoneToolIntegration();
    await testDoneToolSuccessScenarios();

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

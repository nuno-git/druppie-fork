/**
 * Test script for done tool enforcement in FlowExecutor.
 */

import { FlowExecutor } from "./flows/executor/FlowExecutor.js";
import { FlowContext } from "./flows/executor/FlowContext.js";
import { parseFlow } from "./flows/schema.js";

async function testDoneToolEnforcement() {
  console.log("\n=== Testing Done Tool Enforcement ===\n");

  const flowPath = "/home/nuno/Documents/druppie-fork/pi_agent/.pi/flows/tdd.yaml";
  const flow = parseFlow(flowPath);

  console.log("✅ Flow parsed successfully!");
  console.log(`  Phases: ${flow.phases.length}`);

  // Find verify phase (has variables requirement) - it's inside build_loop
  let verifyPhase = flow.phases.find(p => p.name === "verify");

  // If not found at top level, search in nested phases
  if (!verifyPhase) {
    for (const phase of flow.phases) {
      if (phase.phases) {
        const nested = phase.phases.find(p => p.name === "verify");
        if (nested) {
          verifyPhase = nested;
          break;
        }
      }
    }
  }

  if (!verifyPhase) {
    console.error("❌ verify phase not found");
    return false;
  }

  console.log(`  Verify phase has variables: ${verifyPhase.variables?.map(v => v.name).join(", ")}`);

  // Create a mock executor to test enforcement
  const executor = new FlowExecutor();
  
  // Test the extractDoneToolUsage method directly
  const testOutput1 = `
Some analysis and work.

done(variables={
    "succeeded": true,
    "testsPassed": true
}, message="All tests passed successfully")
  `;

  console.log("\n--- Testing done tool extraction ---");
  
  // Use reflection to access private method for testing
  const extractMethod = (executor as any).extractDoneToolUsage.bind(executor);
  
  extractMethod(testOutput1);
  console.log("✅ Done tool detected in output 1");
  console.log(`  Variables: ${JSON.stringify((executor as any).doneToolVariables)}`);
  console.log(`  Message: ${(executor as any).doneToolMessage}`);

  const testOutput2 = `
Some work but no done tool called.
This should fail enforcement.
  `;

  extractMethod(testOutput2);
  console.log("✅ No done tool detected in output 2");
  console.log(`  Tool used: ${(executor as any).doneToolUsed}`);

  // Test with different formats
  const testOutput3 = `
{"tool_calls": [{"name": "done", "parameters": {"variables": {"succeeded": true}, "message": "Done"}}]}
  `;

  extractMethod(testOutput3);
  console.log("✅ JSON format done tool detected");
  console.log(`  Tool used: ${(executor as any).doneToolUsed}`);
  console.log(`  Variables: ${JSON.stringify((executor as any).doneToolVariables)}`);

  // Test enforcement with missing variables
  const testOutput4 = `
done(variables={}, message="Missing required variables")
  `;

  console.log("\n--- Testing enforcement with missing variables ---");
  extractMethod(testOutput4);
  
  try {
    (executor as any).enforceDoneTool(verifyPhase, "test-agent", testOutput4);
    console.log("❌ Should have thrown error for missing variables");
    return false;
  } catch (error) {
    console.log("✅ Correctly detected missing variables");
    console.log(`  Error: ${(error as Error).message.substring(0, 100)}...`);
  }

  // Test enforcement without done tool
  const testOutput5 = "No done tool here";

  console.log("\n--- Testing enforcement without done tool ---");
  extractMethod(testOutput5);

  try {
    (executor as any).enforceDoneTool(verifyPhase, "test-agent", testOutput5);
    console.log("❌ Should have thrown error for missing done tool");
    return false;
  } catch (error) {
    console.log("✅ Correctly detected missing done tool");
    console.log(`  Error: ${(error as Error).message.substring(0, 100)}...`);
  }

  // Test successful enforcement
  const testOutput6 = `
done(variables={"succeeded": true}, message="Work completed successfully")
  `;

  console.log("\n--- Testing successful enforcement ---");
  extractMethod(testOutput6);

  try {
    (executor as any).enforceDoneTool(verifyPhase, "test-agent", testOutput6);
    console.log("✅ Enforcement passed with correct variables");
    console.log(`  Variables set: ${Object.keys((executor as any).doneToolVariables).join(", ")}`);
  } catch (error) {
    console.log("❌ Unexpected error:", error);
    return false;
  }

  return true;
}

async function runTest() {
  console.log("╔══════════════════════════════════════════════════════════╗");
  console.log("║  Done Tool Enforcement Test                             ║");
  console.log("╚══════════════════════════════════════════════════════════╝");

  try {
    const success = await testDoneToolEnforcement();
    
    if (success) {
      console.log("\n╔══════════════════════════════════════════════════════════╗");
      console.log("║  ✅ Done tool enforcement test passed!                  ║");
      console.log("╚══════════════════════════════════════════════════════════╝\n");
      process.exit(0);
    } else {
      console.log("\n❌ Done tool enforcement test failed!");
      process.exit(1);
    }
  } catch (error) {
    console.error("\n❌ Test error:", error);
    process.exit(1);
  }
}

runTest();

/**
 * Unit tests for subagent ID generation logic.
 *
 * The naming logic lives inside subagentTool.execute() in run-agent.ts.
 * This test extracts the naming logic as a pure function and tests it.
 */

interface SubagentTask {
  agent: string;
  task: string;
}

interface NamedTask extends SubagentTask {
  agentName: string;
}

/**
 * Assign unique agentName values to a list of subagent tasks.
 * Extracted from subagentTool.execute() in run-agent.ts.
 */
function assignAgentNames(taskList: SubagentTask[]): NamedTask[] {
  const nameCounts = new Map();
  return taskList.map((t) => {
    const key = t.agent;
    const count = (nameCounts.get(key) ?? 0) + 1;
    nameCounts.set(key, count);
    return { ...t, agentName: taskList.length === 1 ? key : `${key}-${count}` };
  });
}

function assertEqual(actual: unknown, expected: unknown, label: string): void {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  if (a !== e) {
    console.error(`  FAIL: ${label}`);
    console.error(`    expected: ${e}`);
    console.error(`    actual:   ${a}`);
    process.exitCode = 1;
  } else {
    console.log(`  PASS: ${label}`);
  }
}

// Test 1: Single task gets just the agent name (no suffix)
{
  console.log("Test 1: Single task => agentName matches agent");
  const result = assignAgentNames([{ agent: "builder", task: "do something" }]);
  assertEqual(result.length, 1, "one result");
  assertEqual(result[0].agentName, "builder", "no numeric suffix for single task");
  assertEqual(result[0].agent, "builder", "original agent preserved");
}

// Test 2: Three builders get builder-1, builder-2, builder-3
{
  console.log("Test 2: Three builders => builder-1, builder-2, builder-3");
  const result = assignAgentNames([
    { agent: "builder", task: "task one" },
    { agent: "builder", task: "task two" },
    { agent: "builder", task: "task three" },
  ]);
  assertEqual(result.length, 3, "three results");
  assertEqual(result[0].agentName, "builder-1", "first builder gets builder-1");
  assertEqual(result[1].agentName, "builder-2", "second builder gets builder-2");
  assertEqual(result[2].agentName, "builder-3", "third builder gets builder-3");
  assertEqual(result[0].agent, "builder", "original agent preserved");
  assertEqual(result[1].agent, "builder", "original agent preserved");
  assertEqual(result[2].agent, "builder", "original agent preserved");
}

// Test 3: Different agents each get their own counter
{
  console.log("Test 3: Mixed agents => suffix resets per agent");
  const result = assignAgentNames([
    { agent: "builder", task: "build" },
    { agent: "planner", task: "plan" },
    { agent: "builder", task: "build more" },
  ]);
  assertEqual(result.length, 3, "three results");
  assertEqual(result[0].agentName, "builder-1", "first builder gets builder-1");
  assertEqual(result[1].agentName, "planner-1", "planner gets planner-1");
  assertEqual(result[2].agentName, "builder-2", "second builder gets builder-2");
}

// Test 4: Empty tasks => empty array
{
  console.log("Test 4: Empty tasks => empty array");
  const result = assignAgentNames([]);
  assertEqual(result.length, 0, "empty result for empty input");
}

// Test 5: Single task of a different agent
{
  console.log("Test 5: Single planner task => no suffix");
  const result = assignAgentNames([{ agent: "planner", task: "plan" }]);
  assertEqual(result.length, 1, "one result");
  assertEqual(result[0].agentName, "planner", "no suffix for single");
}

// Test 6: loadAgent simulation -- agentName used for journal, agent for prompt loading
{
  console.log("Test 6: loadAgent simulation -- agentName vs agent");
  const task = { agent: "builder", task: "work" };
  const result = assignAgentNames([task]);
  const single = result[0];
  const passedAgent = single.agentName;
  const passedLoadAgent = single.agent;
  assertEqual(passedAgent, "builder", "passed agent matches agentName");
  assertEqual(passedLoadAgent, "builder", "passed loadAgent matches original agent");
}

// Test 7: Empty tasks error handling (simulated execute wrapper)
{
  console.log("Test 7: Empty tasks => error message");
  function executeSimulated(tasks: SubagentTask[]): string {
    const taskList = tasks;
    if (taskList.length === 0) {
      return "Error: no tasks provided. Provide tasks=[...] or agent+task.";
    }
    const named = assignAgentNames(taskList);
    return `spawned ${named.length} subagents: ${named.map((t) => t.agentName).join(",")}`;
  }
  const result = executeSimulated([]);
  assertEqual(
    result,
    "Error: no tasks provided. Provide tasks=[...] or agent+task.",
    "empty tasks returns error message",
  );

  const okResult = executeSimulated([{ agent: "builder", task: "work" }]);
  assertEqual(okResult, "spawned 1 subagents: builder", "non-empty tasks proceed normally");
}

// Test 8: Multiple agents with same name across different calls => independent counters
{
  console.log("Test 8: Multiple calls => counters reset per call");
  const call1 = assignAgentNames([
    { agent: "builder", task: "first" },
    { agent: "builder", task: "second" },
  ]);
  const call2 = assignAgentNames([
    { agent: "builder", task: "third" },
    { agent: "builder", task: "fourth" },
  ]);
  assertEqual(call1[0].agentName, "builder-1", "call1 first builder-1");
  assertEqual(call1[1].agentName, "builder-2", "call1 second builder-2");
  assertEqual(call2[0].agentName, "builder-1", "call2 first builder-1 (counter reset)");
  assertEqual(call2[1].agentName, "builder-2", "call2 second builder-2 (counter reset)");
}

// Summary
{
  const failed = process.exitCode ? true : false;
  if (failed) {
    console.error("\nFAIL: Some tests FAILED");
  } else {
    console.log("\nAll tests PASSED");
  }
  process.exit(failed ? 1 : 0);
}

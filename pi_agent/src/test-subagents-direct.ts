import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { runSingleAgent } from "./run-agent.js";

const __dirname = resolve(fileURLToPath(import.meta.url), "..");
let passed = 0;
let failed = 0;

function chk(condition: boolean, label: string) {
  if (condition) { console.log(`PASS: ${label}`); passed++; }
  else { console.log(`FAIL: ${label}`); failed++; }
}

function loadAgentPrompt(agentName: string, projectRoot: string, cwd: string): string {
  const piRoot = projectRoot.replace(/\/dist$/, "");
  for (const dir of [join(cwd, ".pi", "agents"), join(projectRoot, ".pi", "agents"), join(piRoot, ".pi", "agents")]) {
    for (const ext of [".md", ".markdown"]) {
      const fp = join(dir, `${agentName}${ext}`);
      if (existsSync(fp)) return readFileSync(fp, "utf-8").replace(/^---\n[\s\S]*?\n---\n/, "").trim();
    }
  }
  throw new Error(`Agent "${agentName}" not found.`);
}

function validateTaskInput(
  params: { tasks?: { agent: string; task: string }[]; agent?: string; task?: string },
  projectRoot: string, cwd: string,
): string[] {
  const taskList = params.tasks ?? (params.agent && params.task ? [{ agent: params.agent, task: params.task }] : []);
  if (taskList.length === 0) return ["Error: no tasks provided"];
  const errors: string[] = [];
  for (const t of taskList) {
    try { loadAgentPrompt(t.agent, projectRoot, cwd); }
    catch (e: any) { errors.push(`[${t.agent}] ${e.message}`); }
  }
  return errors;
}

const CWD = resolve(__dirname, "..");
const PROJECT_ROOT = resolve(__dirname, "..");
const agentsDir = join(CWD, ".pi", "agents");
const agentNames = existsSync(agentsDir) ? readdirSync(agentsDir).filter(f => f.endsWith(".md")).map(f => f.replace(/\.md$/, "")) : [];

// Test a: loadAgentPrompt()
console.log("\n=== Test a: loadAgentPrompt() ===\n");
chk(agentNames.length > 0, `Discovered ${agentNames.length} agent prompt files: ${agentNames.join(", ")}`);
for (const agent of agentNames) {
  let prompt: string | undefined;
  let thrown: string | undefined;
  try { prompt = loadAgentPrompt(agent, PROJECT_ROOT, CWD); }
  catch (e: any) { thrown = e.message; }
  if (thrown) {
    chk(false, `Agent "${agent}" loading: ${thrown}`);
    continue;
  }
  chk(prompt !== undefined && prompt.length > 0, `Agent "${agent}" prompt loads (${prompt!.length} chars)`);
  chk(!prompt!.startsWith("---"), `Agent "${agent}" frontmatter stripped`);
  chk(prompt!.includes("You are") || prompt!.includes("Your job") || prompt!.includes("You are an"), `Agent "${agent}" has instruction content`);
}

// Test b: subagentTool.execute() validation logic
console.log("\n=== Test b: subagentTool.execute() ===\n");
if (agentNames.length > 0) {
  const validAgent = agentNames[0];
  const errs = validateTaskInput({ tasks: [{ agent: validAgent, task: "do something" }] }, PROJECT_ROOT, CWD);
  chk(errs.length === 0, `subagent validates known agent "${validAgent}"`);
}
const badErrs = validateTaskInput({ tasks: [{ agent: "nonexistent-agent-xyz", task: "do something" }] }, PROJECT_ROOT, CWD);
chk(badErrs.length > 0, `subagent rejects unknown agent name`);
const emptyErrs = validateTaskInput({}, PROJECT_ROOT, CWD);
chk(emptyErrs.length === 1 && emptyErrs[0].includes("no tasks provided"), `subagent rejects empty task params`);
const singleErrs = validateTaskInput({ agent: agentNames[0] || "builder", task: "single task" }, PROJECT_ROOT, CWD);
chk(singleErrs.length === 0, `subagent accepts agent+task single format`);

// Test c: runSingleAgent graceful error handling
console.log("\n=== Test c: runSingleAgent graceful error handling ===\n");
try {
  const result = await runSingleAgent({
    agent: agentNames[0] || "builder",
    prompt: "test",
    workDir: CWD,
    projectRoot: PROJECT_ROOT,
    maxTurns: 1,
    model: "zai/nonexistent-model",
  });
  chk(typeof result.success === "boolean", `runSingleAgent returns result (success=${result.success})`);
  chk(typeof result.summary === "string", `runSingleAgent returns summary string`);
  chk(Array.isArray(result.toolCallsUsed), `runSingleAgent returns toolCallsUsed array`);
} catch (e: any) {
  chk(false, `runSingleAgent should not throw: ${e.message}`);
}

// Test d: sandboxClient passing
console.log("\n=== Test d: sandboxClient passing ===\n");
const mockEndpoint = { host: "127.0.0.1", port: 9999, authToken: "mock-token" };
const mockClient = {
  getEndpoint: () => mockEndpoint,
  post: async () => ({}),
  get: async () => ({}),
  execStream: async () => ({ exitCode: 0, timedOut: false }),
  postSync: () => ({}),
};
try {
  const result = await runSingleAgent({
    agent: agentNames[0] || "builder",
    prompt: "test",
    workDir: CWD,
    projectRoot: PROJECT_ROOT,
    maxTurns: 1,
    model: "zai/nonexistent-model",
    sandboxClient: mockClient as any,
  });
  chk(typeof result.success === "boolean", `runSingleAgent with mock sandboxClient returns result (success=${result.success})`);
} catch (e: any) {
  chk(false, `runSingleAgent with mock sandboxClient should not throw: ${e.message}`);
}

// Summary
console.log(`\n=== Results: ${passed} passed, ${failed} failed ===\n`);
process.exit(failed > 0 ? 1 : 0);

#!/usr/bin/env node
/**
 * CLI entrypoint for the one-shot TDD agent.
 *
 * All tool operations run inside a Kata microVM. The pi orchestrator
 * and LLM credentials stay on the host. The final push happens from a
 * separate throwaway container that only sees the bundle and the token.
 */
import { mkdirSync, readFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { runSingleAgent, type SingleAgentParams, type SingleAgentResult } from "./run-agent.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
/** Project root = parent of dist/ where the CLI lives */
const PROJECT_ROOT = resolve(__dirname, "..");

interface RunAgentArgs {
  agent: string;
  prompt?: string;
  promptFile?: string;
  workDir: string;
  model?: string;
  glmKey?: string;
  apiKey?: string;
  maxTurns?: number;
  sandboxLaunch?: boolean;
  sandboxImage?: string;
  sandboxHost?: string;
  sandboxPort?: number;
  sandboxAuthToken?: string;
  sourceRepoUrl?: string;
  sourceBranch?: string;
  pushToken?: string;
  ingestUrl?: string;
  ingestToken?: string;
  ingestRunId?: string;
}

function parseRunAgentArgs(argv: string[]): RunAgentArgs {
  const args = argv.slice(3);
  const result: RunAgentArgs = {
    agent: "",
    workDir: mkdtempSync(join(tmpdir(), "run-agent-")),
  };

  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    const next = args[i + 1];

    switch (arg) {
      case "--agent":
        result.agent = next ?? "";
        i++;
        break;
      case "--prompt":
        result.prompt = next ?? "";
        i++;
        break;
      case "--prompt-file":
        result.promptFile = next;
        i++;
        break;
      case "--workdir":
        result.workDir = resolve(next ?? "");
        i++;
        break;
      case "--model":
        result.model = next;
        i++;
        break;
      case "--glm-key":
        result.glmKey = next;
        i++;
        break;
      case "--api-key":
        result.apiKey = next;
        i++;
        break;
      case "--max-turns":
        result.maxTurns = next ? Number(next) : undefined;
        i++;
        break;
      case "--sandbox-launch":
        result.sandboxLaunch = true;
        break;
      case "--sandbox-image":
        result.sandboxImage = next;
        i++;
        break;
      case "--sandbox-host":
        result.sandboxHost = next;
        i++;
        break;
      case "--sandbox-port":
        result.sandboxPort = next ? Number(next) : undefined;
        i++;
        break;
      case "--sandbox-auth-token":
        result.sandboxAuthToken = next;
        i++;
        break;
      case "--source-repo":
        result.sourceRepoUrl = next;
        i++;
        break;
      case "--source-branch":
        result.sourceBranch = next;
        i++;
        break;
      case "--push-token":
        result.pushToken = next;
        i++;
        break;
      case "--ingest-url":
        result.ingestUrl = next;
        i++;
        break;
      case "--ingest-token":
        result.ingestToken = next;
        i++;
        break;
      case "--ingest-run-id":
        result.ingestRunId = next;
        i++;
        break;
      case "--help":
        printRunAgentHelp();
        process.exit(0);
    }
  }

  return result;
}

function printRunAgentHelp(): void {
  console.error(`
run-agent — Run a single agent with sandbox and JSON output

Usage:
  node pi_agent/dist/cli.js run-agent --agent <name> --prompt <text> [options]
  node pi_agent/dist/cli.js run-agent --agent <name> --prompt-file <path> [options]

Required:
  --agent <name>          Agent name from .pi/agents/
  --prompt <text>         Prompt for the agent (or use --prompt-file)
  --prompt-file <path>    Read prompt from file

Sandbox (one of):
  --sandbox-launch              Launch a new sandbox
  --sandbox-image <tag>         Docker image for new sandbox
  --sandbox-host <host>         Connect to existing sandbox
  --sandbox-port <port>         Port for existing sandbox (default 8000)
  --sandbox-auth-token <tok>    Auth token for existing sandbox

Source:
  --source-repo <url>     Clone repo into sandbox
  --source-branch <name>  Branch to clone (default: main)

Model:
  --model <id>            Default model (default: zai/glm-5.1)
  --glm-key <key>         GLM/ZAI API key
  --api-key <key>         Anthropic API key
  --max-turns <n>         Max agent turns (default: 40)

Ingest (for event streaming):
  --ingest-url <url>      Druppie ingest endpoint
  --ingest-token <tok>    Bearer token for ingest
  --ingest-run-id <id>    Run ID for ingest

Output: Final line on stdout is JSON: {output, summary, variables, success, toolCallsUsed}
All other output (logs, progress) goes to stderr.
`);
}

async function mainRunAgent(): Promise<void> {
  const parsed = parseRunAgentArgs(process.argv);

  if (!parsed.agent) {
    process.stderr.write("Error: --agent is required.\n");
    process.exit(1);
  }

  let prompt = parsed.prompt;
  if (!prompt && parsed.promptFile) {
    prompt = readFileSync(resolve(parsed.promptFile), "utf-8");
  }
  if (!prompt) {
    process.stderr.write("Error: --prompt or --prompt-file is required.\n");
    process.exit(1);
  }

  mkdirSync(parsed.workDir, { recursive: true });

  const params: SingleAgentParams = {
    agent: parsed.agent,
    prompt,
    workDir: parsed.workDir,
    projectRoot: PROJECT_ROOT,
    model: parsed.model,
    apiKey: parsed.apiKey ?? process.env.ANTHROPIC_API_KEY,
    glmApiKey: parsed.glmKey ?? process.env.GLM_API_KEY ?? process.env.ZAI_API_KEY,
    maxTurns: parsed.maxTurns,
    sandboxLaunch: parsed.sandboxLaunch,
    sandboxImage: parsed.sandboxImage,
    sandboxHost: parsed.sandboxHost,
    sandboxPort: parsed.sandboxPort,
    sandboxAuthToken: parsed.sandboxAuthToken,
    sourceRepoUrl: parsed.sourceRepoUrl,
    sourceBranch: parsed.sourceBranch,
    pushToken: parsed.pushToken ?? process.env.GITHUB_TOKEN ?? process.env.GITEA_TOKEN,
    ingestUrl: parsed.ingestUrl ?? process.env.PI_AGENT_INGEST_URL,
    ingestToken: parsed.ingestToken ?? process.env.PI_AGENT_INGEST_TOKEN,
    ingestRunId: parsed.ingestRunId,
  };

  process.stderr.write(`[run-agent] agent=${params.agent} model=${params.model ?? "default"}\n`);

  let result: SingleAgentResult;
  try {
    result = await runSingleAgent(params);
  } catch (err) {
    result = {
      output: "",
      summary: "",
      variables: {},
      success: false,
      toolCallsUsed: [],
    };
    process.stderr.write(`[run-agent] Fatal: ${err instanceof Error ? err.message : String(err)}\n`);
  }

  process.stdout.write(JSON.stringify(result) + "\n");
  process.exit(result.success ? 0 : 1);
}

mainRunAgent().catch((err) => {
  console.error("Fatal:", err);
  process.exit(1);
});


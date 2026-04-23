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
import { runOneShotAgent } from "./agent.js";
import { loadAppCredentialsFromEnv } from "./github/app.js";
import type { AgentConfig, TaskSpec } from "./types.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
/** Project root = parent of dist/ where the CLI lives */
const PROJECT_ROOT = resolve(__dirname, "..");

interface ParsedArgs {
  task?: TaskSpec;
  taskFile?: string;
  workDir: string;
  model?: string;
  thinkingLevel?: string;
  skillPaths: string[];
  push: boolean;
  glmKey?: string;
  sandboxImage?: string;
  sandboxPushImage?: string;
  sandboxRemoteUrl?: string;
  sandboxPushToken?: string;
  prBase?: string;
  prTitle?: string;
  sourceRepoUrl?: string;
  sourceBranch?: string;
}

function parseArgs(argv: string[]): ParsedArgs {
  const args = argv.slice(2);
  const result: ParsedArgs = {
    // The host workDir is used only by pi's resource loader for session
    // scaffolding — the actual agent workspace lives inside the sandbox
    // (/workspace). An empty tmpdir per run keeps host state clean.
    workDir: mkdtempSync(join(tmpdir(), "oneshot-")),
    skillPaths: [],
    push: false,
  };

  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    const next = args[i + 1];

    switch (arg) {
      case "--task":
        if (next?.endsWith(".json")) {
          result.taskFile = next;
        } else if (next) {
          result.task = { description: next, language: "typescript" };
        }
        i++;
        break;
      case "--lang":
        if (result.task) result.task.language = next;
        i++;
        break;
      case "--workdir":
        result.workDir = resolve(next);
        i++;
        break;
      case "--model":
        result.model = next;
        i++;
        break;
      case "--thinking":
        result.thinkingLevel = next;
        i++;
        break;
      case "--skills":
        result.skillPaths.push(resolve(next));
        i++;
        break;
      case "--push":
        result.push = true;
        break;
      case "--glm-key":
        result.glmKey = next;
        i++;
        break;
      case "--sandbox-image":
        result.sandboxImage = next;
        i++;
        break;
      case "--sandbox-push-image":
        result.sandboxPushImage = next;
        i++;
        break;
      case "--push-remote":
        result.sandboxRemoteUrl = next;
        i++;
        break;
      case "--push-token":
        result.sandboxPushToken = next;
        i++;
        break;
      case "--pr-base":
        result.prBase = next;
        i++;
        break;
      case "--pr-title":
        result.prTitle = next;
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
      case "--help":
        printHelp();
        process.exit(0);
    }
  }

  return result;
}

function printHelp(): void {
  console.log(`
oneshot-tdd-agent — One-shot TDD coding agent (Kata-sandboxed)

Usage:
  oneshot --task <file.json>                  Run from task file
  oneshot --task "description" --lang <lang>  Run inline task

All tool operations run inside a Kata microVM. Your LLM key stays on the host.

Options:
  --task <file|desc>   Task JSON file or inline description
  --lang <language>    Language (default: typescript)
  --workdir <path>     Host scratch dir for pi resource loading (default: tmpdir)
  --model <id>         Default model: "provider/id" or just "id"
  --thinking <level>   off|minimal|low|medium|high (default: medium)
  --glm-key <key>      GLM Coding API key (or set GLM_API_KEY env)
  --skills <path>      Additional skill directory (repeatable)
  --push               Push to remote on completion (requires --push-remote + token)
  --push-remote <url>  https://github.com/org/repo
  --push-token <tok>   GitHub token for push container (or \$GITHUB_TOKEN)
  --pr-base <branch>   Auto-ensure an open PR into this branch.
                       Default: --source-branch (i.e. PR back to where you started).
                       If already open → no-op. Needs token with PR:write.
  --pr-title <title>   Override default PR title (default: task description)
  --source-repo <url>  Clone this repo into the sandbox before the agent runs.
                       https://github.com/org/repo — auth via GitHub App or PAT.
  --source-branch <b>  Branch in --source-repo to base the agent's work on.
                       Default: colab-dev
  --sandbox-image <t>  Image tag for the sandbox daemon (default oneshot-sandbox:latest)
  --sandbox-push-image <t>  Image tag for the push container (default oneshot-push-sandbox:latest)
  --help               Show this help

Requirements:
  - Docker with Kata Containers registered as a runtime (kata-runtime).
    https://github.com/kata-containers/kata-containers/blob/main/docs/install/docker/

Environment:
  GLM_API_KEY / ZAI_API_KEY Z.AI key — REQUIRED with the default agent config
                            (all four agents in .pi/agents/ use zai/glm-5.1)
  ANTHROPIC_API_KEY         Only needed if you edit an agent's frontmatter to
                            use a Claude model
  GITHUB_TOKEN              PAT fallback for push & PR ops
  GITHUB_APP_ID             } GitHub App path (preferred if all three set):
  GITHUB_APP_INSTALLATION_ID} mints a ~1h installation token per run.
  GITHUB_APP_PRIVATE_KEY_PATH} Path to the App private-key PEM.

Build images once:
  ./scripts/build-sandboxes.sh
  `);
}

async function main(): Promise<void> {
  const parsed = parseArgs(process.argv);

  let task: TaskSpec;
  if (parsed.taskFile) {
    const content = readFileSync(resolve(parsed.taskFile), "utf-8");
    task = JSON.parse(content) as TaskSpec;
  } else if (parsed.task) {
    task = parsed.task;
  } else {
    console.error("Error: --task is required. Use --help for usage.");
    process.exit(1);
  }

  if (parsed.push) task.pushOnComplete = true;
  if (parsed.sourceRepoUrl) task.sourceRepoUrl = parsed.sourceRepoUrl;
  if (parsed.sourceBranch) task.sourceBranch = parsed.sourceBranch;

  mkdirSync(parsed.workDir, { recursive: true });

  const config: AgentConfig = {
    workDir: parsed.workDir,
    projectRoot: PROJECT_ROOT,
    model: parsed.model,
    thinkingLevel: parsed.thinkingLevel as AgentConfig["thinkingLevel"],
    apiKey: process.env.ANTHROPIC_API_KEY,
    // Accept either GLM_API_KEY or ZAI_API_KEY — same upstream provider
    // (Z.AI), different naming conventions in the ecosystem.
    glmApiKey: parsed.glmKey ?? process.env.GLM_API_KEY ?? process.env.ZAI_API_KEY,
    skillPaths: parsed.skillPaths,
    sandbox: {
      image: parsed.sandboxImage,
      pushImage: parsed.sandboxPushImage,
      remoteUrl: parsed.sandboxRemoteUrl,
      // GitHub App auth is picked up automatically by the git-provider layer
      // (see pi_agent/src/git/provider.ts). When PI_AGENT_GIT_PROVIDER=gitea,
      // that layer uses GITEA_TOKEN instead. Keep loadAppCredentialsFromEnv()
      // here to pre-populate config.sandbox.githubApp for legacy code that
      // still reads it (e.g. bundle-push), but all new auth flows go through
      // the provider.
      githubApp: loadAppCredentialsFromEnv() ?? undefined,
      pushToken: parsed.sandboxPushToken ?? process.env.GITHUB_TOKEN ?? process.env.GITEA_TOKEN,
      prBase: parsed.prBase,
      prTitle: parsed.prTitle,
    },
  };

  console.log("=".repeat(60));
  console.log("  oneshot-tdd-agent (kata-sandboxed)");
  console.log("=".repeat(60));
  console.log(`  Task:      ${task.description}`);
  console.log(`  Language:  ${task.language}`);
  console.log(`  WorkDir:   ${config.workDir}`);
  console.log("=".repeat(60));
  console.log();

  const result = await runOneShotAgent(task, config);

  console.log();
  console.log("=".repeat(60));
  console.log("  RESULT");
  console.log("=".repeat(60));
  console.log(`  Success:   ${result.success}`);
  console.log(`  Branch:    ${result.branch}`);
  console.log(`  Commits:   ${result.commits.length}`);
  console.log(`  Tests:     ${result.testsPassed ? "PASSED" : "UNKNOWN"}`);
  console.log(`  Build:     ${result.buildPassed ? "PASSED" : "UNKNOWN"}`);
  if (result.plan) {
    const totalSteps = result.plan.waves.reduce((n, w) => n + w.length, 0);
    console.log(`  Plan:      ${result.plan.waves.length} waves, ${totalSteps} steps`);
  }
  console.log(`  Steps:     ${result.stepResults.filter((r) => r.success).length}/${result.stepResults.length} passed`);
  console.log(`  Iterations: ${result.iterations}`);
  if (result.errors.length > 0) {
    console.log(`  Errors:`);
    result.errors.forEach((e) => console.log(`    - ${e}`));
  }
  console.log(`  Summary:   ${result.summary}`);
  console.log("=".repeat(60));

  process.exit(result.success ? 0 : 1);
}

main().catch((err) => {
  console.error("Fatal:", err);
  process.exit(1);
});

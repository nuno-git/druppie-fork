/**
 * Orchestrator — plain-code coordinator. NOT an LLM agent.
 *
 * Every decision here is deterministic (for-loops, JSON boolean checks).
 * The LLM is only called by the four real agents in .pi/agents/:
 *   analyst, planner, builder, verifier.
 * This file just sequences them in a fixed state machine:
 *
 *   1. ANALYZE   →  call analyst once, parse GoalAnalysis JSON
 *   2. PLAN      →  call planner, parse BuildPlan JSON
 *   3. EXECUTE   →  call builder per wave (sequentially or in parallel)
 *   4. VERIFY    →  call verifier, parse VerificationResult JSON
 *        │
 *        ├─ testsPassed && buildPassed  → break
 *        └─ otherwise                    → back to PLAN with fix context
 *
 * PLAN → EXECUTE → VERIFY loops up to `maxIterations`. Each retry, the
 * planner receives the verifier's remainingIssues as context for a
 * targeted fix plan.
 *
 * The orchestrator commits nothing. Every real commit is made by an
 * agent running `git commit` via bash inside the sandbox.
 */
import { join } from "node:path";
import type { Api, Model } from "@mariozechner/pi-ai";
import { AuthStorage, ModelRegistry } from "@mariozechner/pi-coding-agent";
import { selectGitProvider, type GitProvider } from "../git/provider.js";
import { Journal, printRunSummary } from "../journal.js";
import { startSimServer, type SimServer } from "../providers/sim.js";
import { pushBundleIsolated } from "../sandbox/bundle-push.js";
import { defaultSandboxLaunchOptions, launchSandbox, type RunningSandbox } from "../sandbox/lifecycle.js";
import { SandboxGitOps } from "../sandbox/sandbox-git.js";
import { cloneSourceIntoSandbox } from "../sandbox/source-clone.js";
import {
  discoverAgents,
  runSubagent,
  runSubagentsParallel,
  type AgentDefinition,
  type RunSubagentOptions,
} from "../agents/runner.js";
import type {
  AgentConfig,
  BuildPlan,
  BuildStep,
  GoalAnalysis,
  RunResult,
  StepResult,
  TaskSpec,
  VerificationResult,
} from "../types.js";

// ── JSON Extraction ─────────────────────────────────────────

function extractJson<T>(output: string): T | null {
  // Try ```json blocks first
  const fenced = output.match(/```json\s*\n([\s\S]*?)\n```/);
  if (fenced) {
    try { return JSON.parse(fenced[1]) as T; } catch { /* fall through */ }
  }
  // Try raw JSON
  const raw = output.match(/(\{[\s\S]*\})/);
  if (raw) {
    try { return JSON.parse(raw[1]) as T; } catch { /* fall through */ }
  }
  return null;
}

// ── Orchestrator ────────────────────────────────────────────

export async function runTddFlow(task: TaskSpec, config: AgentConfig): Promise<RunResult> {
  const cwd = config.workDir;
  const maxIterations = config.maxIterations ?? 3;
  const commits: string[] = [];
  const errors: string[] = [];
  const allStepResults: StepResult[] = [];

  // ── Journal setup ──
  const runTimestamp = new Date().toISOString().replace(/[:.]/g, "-");
  const runsRoot = config.projectRoot ? join(config.projectRoot, "sessions", "runs") : join(cwd, "runs");
  const journalDir = join(runsRoot, runTimestamp);
  const journal = new Journal(journalDir, task);

  // ── Git provider (GitHub App vs Gitea) ──
  const gitProvider = selectGitProvider();
  journal.write("git_provider_selected", { kind: gitProvider.kind });

  // ── Sandbox lifecycle (always on) ──
  const launchOpts = {
    ...defaultSandboxLaunchOptions(),
    ...(config.sandbox?.image ? { image: config.sandbox.image } : {}),
    ...(config.sandbox?.memoryLimit ? { memoryLimit: config.sandbox.memoryLimit } : {}),
    ...(config.sandbox?.cpuLimit ? { cpuLimit: config.sandbox.cpuLimit } : {}),
    ...(config.sandbox?.pidsLimit ? { pidsLimit: config.sandbox.pidsLimit } : {}),
    ...(config.sandbox?.allowNetwork !== undefined ? { allowNetwork: config.sandbox.allowNetwork } : {}),
    ...(config.sandbox?.timeoutSec ? { timeoutSec: config.sandbox.timeoutSec } : {}),
  };
  console.log(`[sandbox] launching ${launchOpts.runtime} (${launchOpts.memoryLimit} mem, ${launchOpts.cpuLimit} cpu)`);
  journal.sandboxStart("(pending)", launchOpts.runtime);
  const sandbox: RunningSandbox = await launchSandbox(launchOpts);
  journal.sandboxReady();
  journal.write("sandbox_ready", { containerName: sandbox.containerName, hostPort: sandbox.hostPort });
  console.log(`[sandbox] ready: ${sandbox.containerName}`);

  // ── Git setup ──
  // If task.sourceRepoUrl is set, mint a token on the host, clone that repo,
  // and ship the bundle into the sandbox. The sandbox still sees no credential
  // and no URL — just opaque packfile bytes. If unset, we initialise an empty
  // repo (original behaviour).
  const git = new SandboxGitOps(sandbox.client);

  if (task.sourceRepoUrl) {
    const cloneToken = await resolvePushToken(config, gitProvider);
    if (!cloneToken) {
      throw new Error(
        "task.sourceRepoUrl set but no credentials: provide sandbox.githubApp or sandbox.pushToken",
      );
    }
    const sourceBranch = task.sourceBranch ?? "colab-dev";
    console.log(`[sandbox] cloning ${task.sourceRepoUrl}@${sourceBranch} into sandbox`);
    journal.sourceClone(task.sourceRepoUrl, sourceBranch);
    await cloneSourceIntoSandbox(
      sandbox.client,
      { host: "127.0.0.1", port: sandbox.hostPort, authToken: sandbox.authToken },
      { remoteUrl: task.sourceRepoUrl, branch: sourceBranch, token: cloneToken },
    );
    console.log(`[sandbox] clone complete`);
  }
  // Always set git user.name/email inside the sandbox (idempotent — /init
  // skips `git init` if .git already exists). Without this, agent-run
  // `git commit` inside the sandbox fails with "Author identity unknown".
  await git.init({ remoteUrl: config.sandbox?.remoteUrl });

  // Remember where the agent started from so we can ask git what it actually
  // committed at the end. Capture the SHA of HEAD NOW (after clone + init,
  // before any agent runs). Everything the agents subsequently commit will
  // be reachable from HEAD but not from this SHA, which is exactly the
  // diff we want.
  const baseSha = await git.getCurrentHash();
  console.log(`[base] ${baseSha}`);

  // Start on a throwaway branch so we never commit onto the source branch
  // (e.g. colab-dev) inside the sandbox. The analyst proposes a semantic name
  // as part of its JSON output, and we rename after analysis runs. If the
  // user pinned `task.branch`, that wins.
  const initialBranch = task.branch ?? `oneshot-run-${Date.now().toString(36)}`;
  await git.createBranch(initialBranch);
  let branch = initialBranch;

  // ── Set up model providers ──
  const authStorage = AuthStorage.create();
  if (config.apiKey) authStorage.setRuntimeApiKey("anthropic", config.apiKey);
  const modelRegistry = ModelRegistry.create(authStorage);

  // Register GLM/Z.AI key if provided (Pi SDK has built-in zai provider)
  if (config.glmApiKey) {
    authStorage.setRuntimeApiKey("zai", config.glmApiKey);
    const zaiModels = modelRegistry.getAll().filter((m) => m.provider === "zai");
    console.log(`  Z.AI: key set (${zaiModels.length} built-in models available)`);
  }

  // Optional: failure-simulation proxy for testing retry resilience.
  // Sits in front of the real Z.AI endpoint and injects random 429/5xx
  // failures at `failureRate`; on the good path, it forwards to real upstream
  // so the agents receive real LLM output.
  let simServer: SimServer | undefined;
  if (process.env.ONESHOT_SIM_FAILURES === "1") {
    const failureRate = Number(process.env.ONESHOT_SIM_FAILURE_RATE ?? 0.5);
    simServer = await startSimServer({ failureRate });
    modelRegistry.registerProvider("zai", { baseUrl: simServer.baseUrl });
    journal.write("sim_server_started", { baseUrl: simServer.baseUrl, failureRate });
    console.log(`[sim] failure-injection proxy on ${simServer.baseUrl} (rate=${failureRate}) — zai/* routed through it`);
  }

  // Resolve default model — used only if an agent's .pi/agents/*.md omits a
  // model: field. All current agents specify zai/glm-5.1, so this fallback is
  // usually dead code; keep it aligned with the agents so no one accidentally
  // introduces an Anthropic dependency by forgetting a frontmatter field.
  const modelSpec = config.model ?? "zai/glm-5.1";
  let defaultModel: Model<Api> | undefined;
  if (modelSpec.includes("/")) {
    const [prov, id] = modelSpec.split("/", 2);
    defaultModel = modelRegistry.find(prov, id);
  } else {
    defaultModel = modelRegistry.getAll().find((m) => m.id === modelSpec);
  }
  if (!defaultModel) throw new Error(`Default model not found: ${modelSpec}`);

  // ── Discover agents ──
  // Look for agents in workspace AND project root
  const extraAgentDirs: string[] = [];
  if (config.projectRoot) {
    const { join } = await import("node:path");
    extraAgentDirs.push(join(config.projectRoot, ".pi", "agents"));
  }
  const agents = discoverAgents(cwd, extraAgentDirs);
  const agentMap = new Map<string, AgentDefinition>();
  for (const a of agents) agentMap.set(a.name, a);

  const getAgent = (name: string): AgentDefinition => {
    const agent = agentMap.get(name);
    if (!agent) throw new Error(`Agent "${name}" not found. Available: ${agents.map((a) => a.name).join(", ")}`);
    return agent;
  };

  // Pi's per-subagent transcripts. Standalone runs keep them next to the
  // journal for easy post-mortem. Under druppie (PI_AGENT_INGEST_URL set)
  // the DB is the source of truth, so route transcripts to an OS tmpdir
  // that gets blown away when the subprocess exits.
  const sessionsDir = process.env.PI_AGENT_INGEST_URL
    ? `/tmp/pi-agent-transcripts-${process.pid}`
    : journalDir;

  const baseOpts: RunSubagentOptions = {
    cwd,
    authStorage,
    modelRegistry,
    defaultModel,
    maxTurns: config.maxTurnsPerAgent ?? 30,
    onOutput: (delta) => process.stdout.write(delta),
    sessionsDir,
    sandboxClient: sandbox?.client,
    journal,
  };

  console.log("=".repeat(60));
  console.log("  ORCHESTRATOR");
  console.log("=".repeat(60));
  console.log(`  Branch:      ${branch}`);
  console.log(`  Default model: ${defaultModel.provider}/${defaultModel.id}`);
  console.log(`  Agents:      ${agents.map((a) => a.name).join(", ")}`);
  console.log(`  Max retries: ${maxIterations}`);
  console.log("=".repeat(60));

  let goalAnalysis: GoalAnalysis | undefined;
  let buildPlan: BuildPlan | undefined;

  // ═══════════════════════════════════════════════════════════
  // PHASE 1: ANALYZE (runs once)
  // ═══════════════════════════════════════════════════════════

  journal.phaseStart("ANALYZE", 0);
  console.log("\n▸ PHASE 1: ANALYZE\n");

  const taskPrompt = [
    `## Task`,
    task.description,
    ``,
    `## Language: ${task.language}`,
    task.testCommand ? `## Test command: ${task.testCommand}` : "",
    task.buildCommand ? `## Build command: ${task.buildCommand}` : "",
    ``,
    `The full repository is cloned at /workspace with every branch available locally.`,
    `Use \`git branch -a\` to see what exists before proposing a branchName — do not reuse an existing name.`,
    ``,
    `Analyze this task and produce your JSON output.`,
  ].filter(Boolean).join("\n");

  const analysisResult = await runSubagent(getAgent("analyst"), taskPrompt, baseOpts);
  journal.recordNarrative("analyst", 0, analysisResult.output);

  if (!analysisResult.success) {
    errors.push(`Analyst failed: ${analysisResult.error ?? "unknown"}`);
    sandbox.stop();
    journal.sandboxStop();
    for (const e of errors) journal.error(e);
    await journal.close(false);
    return result(false, branch, commits, errors, allStepResults, 0, goalAnalysis, buildPlan);
  }

  goalAnalysis = extractJson<GoalAnalysis>(analysisResult.output) ?? undefined;
  if (!goalAnalysis) {
    errors.push("Analyst did not produce valid JSON output");
    sandbox.stop();
    journal.sandboxStop();
    for (const e of errors) journal.error(e);
    await journal.close(false);
    return result(false, branch, commits, errors, allStepResults, 0, goalAnalysis, buildPlan);
  }

  // Let the analyst pick the branch name — unless the user pinned task.branch.
  // No fallbacks: if the name is missing, invalid, or collides, fail loud.
  if (!task.branch) {
    if (!goalAnalysis.branchName) {
      throw new Error("analyst did not provide a branchName in its JSON output");
    }
    if (!isSafeBranchName(goalAnalysis.branchName)) {
      throw new Error(`analyst proposed unsafe branch name "${goalAnalysis.branchName}"`);
    }
    await git.renameCurrentBranch(goalAnalysis.branchName);
    journal.branchRenamed(branch, goalAnalysis.branchName);
    branch = goalAnalysis.branchName;
    console.log(`[branch] ${branch}`);
  }

  console.log(`\n✓ Analysis: ${goalAnalysis.tests.length} tests, ${goalAnalysis.criteria.length} criteria, branch=${branch}\n`);

  // ═══════════════════════════════════════════════════════════
  // PLAN → EXECUTE → VERIFY LOOP
  // ═══════════════════════════════════════════════════════════

  let lastVerification: VerificationResult | undefined;
  let iteration = 0;

  for (iteration = 1; iteration <= maxIterations; iteration++) {
    const isRetry = iteration > 1;
    const tag = isRetry ? ` (retry ${iteration - 1})` : "";

    // ─── PLAN ────────────────────────────────────────────────

    journal.phaseStart("PLAN", iteration);
    console.log(`\n▸ PLAN${tag}\n`);

    const planPrompt = isRetry && lastVerification
      ? buildFixPlanPrompt(goalAnalysis, lastVerification, task)
      : buildInitialPlanPrompt(goalAnalysis, task);

    const planResult = await runSubagent(getAgent("planner"), planPrompt, baseOpts);
    journal.recordNarrative("planner", iteration, planResult.output);

    if (!planResult.success) {
      errors.push(`Planner failed${tag}: ${planResult.error ?? "unknown"}`);
      continue; // try again next iteration with same context
    }

    buildPlan = extractJson<BuildPlan>(planResult.output) ?? undefined;
    if (!buildPlan?.waves?.length) {
      errors.push(`Planner produced invalid plan${tag}`);
      continue;
    }

    const totalSteps = buildPlan.waves.reduce((n, w) => n + w.length, 0);
    console.log(`\n✓ Plan: ${buildPlan.waves.length} waves, ${totalSteps} steps\n`);

    // ─── EXECUTE ─────────────────────────────────────────────

    journal.phaseStart("EXECUTE", iteration);
    console.log(`\n▸ EXECUTE${tag}\n`);

    const iterationStepResults = await executeWaves(buildPlan, getAgent("builder"), baseOpts, errors);
    allStepResults.push(...iterationStepResults);
    for (const sr of iterationStepResults) {
      journal.recordNarrative(`builder/${sr.stepId}`, iteration, sr.output);
    }

    const passed = iterationStepResults.filter((r) => r.success).length;
    console.log(`\n✓ Execution: ${passed}/${iterationStepResults.length} steps succeeded\n`);

    // ─── VERIFY ──────────────────────────────────────────────

    journal.phaseStart("VERIFY", iteration);
    console.log(`\n▸ VERIFY${tag}\n`);

    const verifyPrompt = buildVerifyPrompt(task, goalAnalysis, buildPlan, iterationStepResults);
    const verifyResult = await runSubagent(getAgent("verifier"), verifyPrompt, baseOpts);
    journal.recordNarrative("verifier", iteration, verifyResult.output);

    lastVerification = extractJson<VerificationResult>(verifyResult.output) ?? undefined;

    // ─── Check result ────────────────────────────────────────

    // `break` on success so we fall through to the push + PR + journal-close
    // code after the loop. `continue` to retry. `return` would skip everything.
    if (!lastVerification) {
      const textPassed = verifyResult.output.includes("VERIFICATION COMPLETE");
      if (textPassed) {
        console.log(`\n✓ All checks passed on iteration ${iteration}\n`);
        lastVerification = { testsPassed: true, buildPassed: true, fixes: [], remainingIssues: [] };
        break;
      }
      errors.push(`Verifier output not parseable (iteration ${iteration})`);
      continue;
    }

    if (lastVerification.testsPassed && lastVerification.buildPassed) {
      console.log(`\n✓ All checks passed on iteration ${iteration}\n`);
      break;
    }

    // Still have issues — log and loop
    const issueCount = lastVerification.remainingIssues.length;
    const fixCount = lastVerification.fixes.length;
    console.log(`\n⟳ Iteration ${iteration}: ${fixCount} fixed, ${issueCount} remaining — ${iteration < maxIterations ? "re-planning..." : "max iterations reached"}\n`);

    if (lastVerification.fixes.length > 0) {
      console.log("  Fixed:");
      for (const fix of lastVerification.fixes) {
        console.log(`    ✓ ${fix}`);
      }
    }
    if (lastVerification.remainingIssues.length > 0) {
      console.log("  Remaining:");
      for (const issue of lastVerification.remainingIssues) {
        console.log(`    ✗ ${issue.description}`);
      }
    }
  }

  // ── Exhausted iterations ──

  const finalTestsPassed = lastVerification?.testsPassed ?? false;
  const finalBuildPassed = lastVerification?.buildPassed ?? false;

  if (lastVerification?.remainingIssues.length) {
    for (const issue of lastVerification.remainingIssues) {
      errors.push(`Unresolved: ${issue.description} (${issue.rootCause})`);
    }
  }

  // ── Push if requested ──
  //
  // The sandbox produces a git bundle; we hand that bundle to a separate,
  // throwaway push-container that has the token. The main sandbox never sees
  // the token; the push container never sees the LLM key.

  if (task.pushOnComplete) {
    try {
      const remoteUrl = config.sandbox?.remoteUrl;
      const token = await resolvePushToken(config, gitProvider);
      if (!remoteUrl || !token) {
        errors.push("Push requested but remoteUrl and (pushToken / githubApp / gitea) are required");
      } else {
        // Trust the sandbox about the current branch: the agent may have
        // renamed or switched branches mid-run. We push whatever is actually
        // checked out right now — but refuse if it's a protected name, to
        // avoid the agent accidentally pushing onto colab-dev / main / etc.
        const livePushBranch = await git.getCurrentBranch();
        if (livePushBranch !== branch) {
          console.log(`[push] branch changed in sandbox: ${branch} → ${livePushBranch}`);
        }
        if (RESERVED_BRANCHES.has(livePushBranch) || livePushBranch === task.sourceBranch) {
          throw new Error(
            `refusing to push onto protected branch "${livePushBranch}". ` +
              `agent must end the run on a feature branch, not the source branch.`,
          );
        }
        branch = livePushBranch;

        // Ask git what the agents actually committed on this branch. Every
        // sha here came from a builder/verifier running `git commit` via bash
        // inside the sandbox — the orchestrator commits nothing.
        const newCommits = await git.listNewCommits(baseSha);
        for (const c of newCommits.reverse()) {
          commits.push(c.sha);
          journal.commit("agent", c.sha, c.message);
        }
        console.log(`[commits] ${commits.length} new commit(s) on ${branch}`);

        console.log("[push] creating bundle in sandbox…");
        const bundleInfo = await git.createBundle();
        const bundleHostPath = join(sandbox.bundleHostDir, bundleInfo.path.split("/").pop() || "run.bundle");
        journal.pushStart(branch, bundleInfo.size);
        console.log(`[push] pushing ${branch} via isolated push-sandbox…`);
        const res = pushBundleIsolated({
          bundleHostPath,
          remoteUrl,
          branch,
          token,
          pushImage: config.sandbox?.pushImage,
        });
        journal.pushDone(branch, res.ok, res.output);
        if (!res.ok) {
          errors.push(`Push failed: ${res.output}`);
        } else {
          console.log(`[push] done\n${res.output}`);

          // ── Ensure a PR exists (idempotent) ──
          // Default PR base = the branch the agent started from (usually colab-dev).
          const prBase = config.sandbox?.prBase ?? task.sourceBranch ?? "colab-dev";
          if (prBase) {
            try {
              // Ask the pr-author agent to write a title + body based on the
              // actual commits/diff. Retry up to 3 times on invalid JSON. If
              // the caller explicitly set prTitle/prBody, skip the agent.
              let authoredTitle: string | undefined = config.sandbox?.prTitle;
              let authoredBody: string | undefined = config.sandbox?.prBody;

              if (!authoredTitle || !authoredBody) {
                const prPrompt = buildPrAuthorPrompt(baseSha, prBase);
                for (let attempt = 1; attempt <= 3; attempt++) {
                  console.log(`[pr-author] attempt ${attempt}/3`);
                  const result = await runSubagent(getAgent("pr-author"), prPrompt, baseOpts);
                  const parsed = extractJson<{ title?: string; body?: string }>(result.output);
                  if (parsed?.title && parsed?.body) {
                    journal.recordNarrative("pr-author", 0, result.output);
                    authoredTitle = authoredTitle ?? parsed.title;
                    authoredBody = authoredBody ?? parsed.body;
                    console.log(`[pr-author] ok — title="${authoredTitle.slice(0, 60)}${authoredTitle.length > 60 ? "…" : ""}"`);
                    break;
                  }
                  console.warn(`[pr-author] attempt ${attempt} produced unusable output`);
                }
                if (!authoredTitle || !authoredBody) {
                  throw new Error("pr-author failed to produce a valid title+body after 3 attempts");
                }
              }

              const pr = await gitProvider.ensurePullRequest({
                remoteUrl,
                head: branch,
                base: prBase,
                token,
                title: authoredTitle,
                body: authoredBody,
              });
              journal.prEnsured(pr.action, pr.number, pr.url, pr.message);
              if (pr.action === "created") {
                console.log(`[pr] created #${pr.number}: ${pr.url}`);
              } else if (pr.action === "exists") {
                console.log(`[pr] already open #${pr.number}: ${pr.url}`);
              } else {
                errors.push(`PR ensure skipped: ${pr.message}`);
              }
            } catch (err) {
              errors.push(`PR ensure failed: ${err instanceof Error ? err.message : String(err)}`);
            }
          }
        }
      }
    } catch (err) {
      errors.push(`Push failed: ${err instanceof Error ? err.message : String(err)}`);
    }
  }

  const success = finalTestsPassed && finalBuildPassed && errors.length === 0;

  for (const e of errors) journal.error(e);
  sandbox.stop();
  journal.sandboxStop();
  if (simServer) {
    const simStats = simServer.stats();
    journal.write("sim_server_stats", { ...simStats });
    console.log(`[sim] final stats: ${simStats.total} total, ${simStats.failed} injected failures, ${simStats.succeeded} proxied successes, byStatus=${JSON.stringify(simStats.byStatus)}`);
    await simServer.stop();
  }

  const { summary } = await journal.close(success);
  printRunSummary(summary, journalDir, branch, summary.pr?.url);

  return result(success, branch, commits, errors, allStepResults, iteration - 1, goalAnalysis, buildPlan, finalTestsPassed, finalBuildPassed);
}

// ═══════════════════════════════════════════════════════════
// Branch-name validation
// ═══════════════════════════════════════════════════════════

const RESERVED_BRANCHES = new Set(["main", "master", "dev", "colab-dev", "feat", "fix"]);

function isSafeBranchName(name: string): boolean {
  if (!name) return false;
  if (RESERVED_BRANCHES.has(name)) return false;
  // Allow a-z, 0-9, /, -, . (but not .., and not starting/ending with /)
  if (!/^[a-z0-9][a-z0-9\-./]*[a-z0-9]$/i.test(name)) return false;
  if (name.includes("..")) return false;
  if (name.includes("//")) return false;
  return true;
}

// ═══════════════════════════════════════════════════════════
// Token resolution — App (preferred) → PAT
// ═══════════════════════════════════════════════════════════

/**
 * Resolve a token fresh on every call. App installation tokens expire in ~1h;
 * a run can easily outlast that (retries, slow provider, etc.), so caching
 * across the whole run causes auth failures at push time on long runs.
 * Minting is a single JWT sign + one API call — cheap.
 */
async function resolvePushToken(config: AgentConfig, provider: GitProvider): Promise<string | undefined> {
  const fromProvider = await provider.resolveToken();
  if (fromProvider) return fromProvider;
  if (config.sandbox?.pushToken) return config.sandbox.pushToken;
  return undefined;
}

// ═══════════════════════════════════════════════════════════
// PR body builder
// ═══════════════════════════════════════════════════════════

function buildPrAuthorPrompt(baseSha: string, prBase: string): string {
  return [
    `## Base reference`,
    ``,
    `The commits this PR introduces are reachable from HEAD but not from ${baseSha}.`,
    `This branch will be merged into \`${prBase}\` on the remote.`,
    ``,
    `## Commands to inspect the work`,
    ``,
    "```bash",
    `git log --oneline ${baseSha}..HEAD`,
    `git log ${baseSha}..HEAD`,
    `git diff --stat ${baseSha}..HEAD`,
    `git diff ${baseSha}..HEAD -- <path>   # for any interesting file`,
    "```",
    ``,
    `Run these, read any file you need for context, then produce your JSON output.`,
  ].join("\n");
}

function buildDefaultPrBody(task: TaskSpec, goal: GoalAnalysis | undefined, commits: string[]): string {
  const parts: string[] = [];
  parts.push(`## Task`);
  parts.push(task.description);
  if (goal?.criteria.length) {
    parts.push(``);
    parts.push(`## Acceptance criteria`);
    for (const c of goal.criteria) parts.push(`- ${c}`);
  }
  if (commits.length) {
    parts.push(``);
    parts.push(`## Commits`);
    parts.push(`${commits.length} commit(s) on this branch.`);
  }
  parts.push(``);
  parts.push(`_Generated by oneshot-tdd-agent._`);
  return parts.join("\n");
}

// ═══════════════════════════════════════════════════════════
// Prompt Builders
// ═══════════════════════════════════════════════════════════

function buildInitialPlanPrompt(goal: GoalAnalysis, task: TaskSpec): string {
  return [
    `## Mode: Initial Plan`,
    ``,
    `## Goal Analysis`,
    "```json",
    JSON.stringify(goal, null, 2),
    "```",
    ``,
    `## Language: ${task.language}`,
    `## Test command: ${goal.verifyCommand}`,
    task.buildCommand ? `## Build command: ${task.buildCommand}` : "",
    ``,
    `Create a build plan with parallel execution waves. Output your JSON.`,
  ].filter(Boolean).join("\n");
}

function buildFixPlanPrompt(goal: GoalAnalysis, verification: VerificationResult, task: TaskSpec): string {
  return [
    `## Mode: Fix Plan`,
    ``,
    `The previous build attempt had issues. The verifier fixed some things but these remain:`,
    ``,
    `## Remaining Issues`,
    "```json",
    JSON.stringify(verification.remainingIssues, null, 2),
    "```",
    ``,
    `## What the verifier already fixed`,
    verification.fixes.map((f) => `- ${f}`).join("\n") || "- (nothing)",
    ``,
    `## Test status: ${verification.testsPassed ? "PASSING" : "FAILING"}`,
    `## Build status: ${verification.buildPassed ? "PASSING" : "FAILING"}`,
    ``,
    `## Original Goal`,
    "```json",
    JSON.stringify(goal, null, 2),
    "```",
    ``,
    `## Language: ${task.language}`,
    `## Test command: ${goal.verifyCommand}`,
    task.buildCommand ? `## Build command: ${task.buildCommand}` : "",
    ``,
    `Create a TARGETED fix plan. Only address the remaining issues.`,
    `Read the existing code first to understand the current state.`,
    `Output your JSON.`,
  ].filter(Boolean).join("\n");
}

function buildVerifyPrompt(task: TaskSpec, goal: GoalAnalysis, plan: BuildPlan, stepResults: StepResult[]): string {
  return [
    `## Project`,
    `Language: ${task.language}`,
    `Test command: ${goal.verifyCommand}`,
    `Build command: ${task.buildCommand ?? "npm run build"}`,
    ``,
    `## What was built`,
    plan.summary,
    ``,
    `## Steps completed`,
    stepResults.map((r) => `- ${r.stepId}: ${r.success ? "✓" : "✗"}`).join("\n"),
    ``,
    `Run the full test suite and build. Fix simple issues yourself.`,
    `For anything you can't fix, describe it precisely in remainingIssues so the planner can create a fix plan.`,
    `Output your JSON result.`,
  ].join("\n");
}

// ═══════════════════════════════════════════════════════════
// Wave Execution
// ═══════════════════════════════════════════════════════════

/**
 * Run each wave of the build plan. The orchestrator does NOT commit —
 * builder/verifier agents commit their own work inside the sandbox via bash,
 * as instructed by their `.pi/agents/*.md` prompts. If an agent forgets to
 * commit, that's their bug to surface, not the orchestrator's to paper over.
 */
async function executeWaves(
  plan: BuildPlan,
  builderAgent: AgentDefinition,
  baseOpts: RunSubagentOptions,
  errors: string[]
): Promise<StepResult[]> {
  const stepResults: StepResult[] = [];

  for (let waveIdx = 0; waveIdx < plan.waves.length; waveIdx++) {
    const wave = plan.waves[waveIdx];
    const parallel = wave.length > 1 ? " (parallel)" : "";
    console.log(`  Wave ${waveIdx + 1}/${plan.waves.length} — ${wave.length} step(s)${parallel}`);

    if (wave.length === 1) {
      const step = wave[0];
      const sr = await executeStep(builderAgent, step, baseOpts);
      stepResults.push(sr);
      if (!sr.success) errors.push(`Step "${step.id}" failed: ${sr.error ?? "unknown"}`);
    } else {
      const tasks = wave.map((step) => ({ agent: builderAgent, prompt: step.prompt }));
      const results = await runSubagentsParallel(tasks, baseOpts);
      for (let i = 0; i < wave.length; i++) {
        const step = wave[i];
        const sub = results[i];
        stepResults.push({
          stepId: step.id,
          success: sub.success,
          output: sub.output,
          filesChanged: step.files,
          error: sub.error,
        });
        if (!sub.success) errors.push(`Step "${step.id}" failed: ${sub.error ?? "unknown"}`);
      }
    }
  }

  return stepResults;
}

async function executeStep(agent: AgentDefinition, step: BuildStep, opts: RunSubagentOptions): Promise<StepResult> {
  const r = await runSubagent(agent, step.prompt, opts);
  return {
    stepId: step.id,
    success: r.success,
    output: r.output,
    filesChanged: step.files,
    error: r.error,
  };
}

// ═══════════════════════════════════════════════════════════
// Result Builder
// ═══════════════════════════════════════════════════════════

function result(
  success: boolean,
  branch: string,
  commits: string[],
  errors: string[],
  stepResults: StepResult[],
  iterations: number,
  goalAnalysis?: GoalAnalysis,
  plan?: BuildPlan,
  testsPassed = false,
  buildPassed = false,
): RunResult {
  return {
    success,
    branch,
    commits,
    testsPassed,
    buildPassed,
    summary: success
      ? `Built successfully on branch ${branch} in ${iterations} iteration(s) (${commits.length} commits)`
      : `Failed after ${iterations} iteration(s) with ${errors.length} error(s) on branch ${branch}`,
    errors,
    plan,
    goalAnalysis,
    stepResults,
    iterations,
  };
}

/**
 * Core types for the multi-agent TDD system.
 */

// ── Task Input ──────────────────────────────────────────────

/** A task specification that the system will build. */
export interface TaskSpec {
  description: string;
  language: string;
  targetDir?: string;
  contextFiles?: string[];
  skills?: string[];
  pushOnComplete?: boolean;
  branch?: string;
  testCommand?: string;
  buildCommand?: string;
  /** If set, the host clones this repo (using sandbox.pushToken or the minted
   * App token) and ships the contents into the sandbox as a git bundle before
   * the agent starts. The sandbox never sees the remote URL or the token. */
  sourceRepoUrl?: string;
  /** Branch in sourceRepoUrl to base the agent's work on. Default: "main". */
  sourceBranch?: string;
}

// ── Build Plan (output of the planner agent) ────────────────

/** A single unit of work in the build plan. */
export interface BuildStep {
  id: string;
  description: string;
  /** Step IDs that must complete before this one starts */
  dependsOn: string[];
  /** Files this step will create or modify */
  files: string[];
  /** The prompt to send to the builder agent */
  prompt: string;
}

/** The full build plan with execution order. */
export interface BuildPlan {
  /** Steps grouped into waves — each wave runs in parallel, waves run sequentially */
  waves: BuildStep[][];
  /** Summary of the overall approach */
  summary: string;
}

// ── Goal Analysis (output of the analyst agent) ─────────────

export interface GoalAnalysis {
  /** Restated, precise goal */
  goal: string;
  /** Acceptance criteria */
  criteria: string[];
  /** Test cases to write (before implementation) */
  tests: TestCase[];
  /** Key architectural decisions */
  architecture: string[];
  /** What test framework/runner to use */
  testFramework: string;
  /** How to verify success */
  verifyCommand: string;
  /** Semantic branch name for this work, kebab-case with conventional prefix
   * (e.g. "feat/add-user-auth", "fix/parser-edge-case"). Orchestrator renames
   * the working branch to this after analysis. */
  branchName?: string;
}

export interface TestCase {
  name: string;
  description: string;
  /** The file this test belongs in */
  file: string;
  /** Whether this is unit, integration, or e2e */
  type: "unit" | "integration" | "e2e";
}

// ── Execution Results ───────────────────────────────────────

export interface StepResult {
  stepId: string;
  success: boolean;
  output: string;
  filesChanged: string[];
  error?: string;
}

// ── Verification (output of the verifier agent) ─────────────

export interface VerificationResult {
  testsPassed: boolean;
  buildPassed: boolean;
  /** Issues the verifier could NOT fix itself */
  remainingIssues: VerificationIssue[];
  /** Issues the verifier DID fix */
  fixes: string[];
}

export interface VerificationIssue {
  /** What's wrong */
  description: string;
  /** Which files are involved */
  files: string[];
  /** Error output / stack trace */
  errorOutput: string;
  /** The verifier's best guess at root cause */
  rootCause: string;
  /** Suggested fix approach for the planner */
  suggestedFix: string;
}

// ── Run Result ──────────────────────────────────────────────

export interface RunResult {
  success: boolean;
  branch: string;
  commits: string[];
  testsPassed: boolean;
  buildPassed: boolean;
  summary: string;
  errors: string[];
  plan?: BuildPlan;
  goalAnalysis?: GoalAnalysis;
  stepResults: StepResult[];
  /** How many plan→execute→verify iterations ran */
  iterations: number;
}

// ── Agent Config ────────────────────────────────────────────

export interface AgentConfig {
  workDir: string;
  /** Directory containing .pi/agents/ definitions (default: dirname of CLI script) */
  projectRoot?: string;
  /** Default model (e.g. "glm-coding/glm-4.5-air" or "claude-sonnet-4-5") */
  model?: string;
  thinkingLevel?: "off" | "minimal" | "low" | "medium" | "high";
  /** Anthropic API key */
  apiKey?: string;
  /** GLM Coding API key */
  glmApiKey?: string;
  skillPaths?: string[];
  maxTurnsPerAgent?: number;
  /** Max plan→execute→verify loop iterations (default: 3) */
  maxIterations?: number;
  /** Sandbox configuration. The sandbox is always on — every tool operation
   * runs inside a Kata microVM. */
  sandbox?: SandboxConfig;
  /** Pi_agent flow to run. "tdd" (default) = analyst→plan→build→verify→PR.
   * "explore" = router + parallel explorers for read-only investigation. */
  flow?: "tdd" | "explore";
}

export interface SandboxConfig {
  /** Docker image tag for the sandbox daemon. Default: "oneshot-sandbox:latest". */
  image?: string;
  /** Docker image tag for the push sandbox. Default: "oneshot-push-sandbox:latest". */
  pushImage?: string;
  memoryLimit?: string; // "4g"
  cpuLimit?: string; // "2"
  pidsLimit?: number;
  /** Allow the sandbox outbound internet (needed for npm/pip install). Default true. */
  allowNetwork?: boolean;
  /** Wall-clock timeout for the whole run (seconds). Default 3600. */
  timeoutSec?: number;
  /** Remote URL to push the final bundle to. If unset, bundle is left on host. */
  remoteUrl?: string;
  /** Short-lived token for the push-sandbox. MUST NOT be injected into the main sandbox.
   * Ignored if `githubApp` is set — the App path mints a fresh installation token per run. */
  pushToken?: string;
  /** GitHub App credentials — used to mint an installation token at run start.
   * Preferred over `pushToken` when both are provided. */
  githubApp?: {
    appId: string;
    installationId: string;
    /** PEM string or filesystem path to the .pem file. */
    privateKey: string;
  };
  /**
   * PR auto-creation. After a successful push, if no open PR exists from the
   * pushed branch to `prBase`, one is created. If a PR already exists, we
   * no-op and log its URL. Set `prBase` to enable.
   */
  prBase?: string; // e.g. "dev" or "main"
  prTitle?: string; // default: task.description
  prBody?: string; // default: task summary + commit list
}

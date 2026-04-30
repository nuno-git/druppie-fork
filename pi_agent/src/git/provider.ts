/**
 * Git-provider abstraction.
 *
 * Originally pi_agent was GitHub-only. When vendored into druppie-fork we
 * also need to run against Gitea project repos, so PR creation + token
 * resolution are behind a small provider interface:
 *
 *   - GitHub (App auth, api.github.com)
 *   - Gitea  (scoped user + static token, ${GITEA_BASE_URL}/api/v1/…)
 *
 * Selection at runtime:
 *   process.env.PI_AGENT_GIT_PROVIDER = "github_app" | "gitea"
 *   (defaults to "github_app" to preserve standalone behaviour)
 *
 * The orchestrator only ever talks to this interface; the github/ and
 * gitea/ modules are implementation detail.
 */
import type { EnsurePrOptions, EnsurePrResult } from "../github/pr.js";
import { ensurePullRequest as ensureGitHubPr, parseRemote } from "../github/pr.js";
import { ensureGiteaPullRequest } from "../gitea/pr.js";
import {
  loadAppCredentialsFromEnv,
  mintInstallationToken,
  type GitHubAppCredentials,
} from "../github/app.js";

export type GitProviderKind = "github_app" | "gitea";

export interface GitProvider {
  kind: GitProviderKind;
  /** Return a short-lived token usable for clone/push and (for GitHub) PR ops. */
  resolveToken(): Promise<string | undefined>;
  /** Idempotent ensure-PR. Same contract as the GitHub implementation. */
  ensurePullRequest(opts: EnsurePrOptions): Promise<EnsurePrResult>;
}

export function selectGitProvider(explicit?: GitProviderKind): GitProvider {
  const kind: GitProviderKind =
    explicit ?? (process.env.PI_AGENT_GIT_PROVIDER as GitProviderKind) ?? "github_app";
  if (kind === "gitea") return createGiteaProvider();
  if (kind === "github_app") return createGitHubProvider();
  throw new Error(`unknown PI_AGENT_GIT_PROVIDER: ${kind}`);
}

// ── GitHub ─────────────────────────────────────────────────────────────────

function createGitHubProvider(): GitProvider {
  const appCreds: GitHubAppCredentials | null = loadAppCredentialsFromEnv();
  return {
    kind: "github_app",
    async resolveToken() {
      if (appCreds) {
        const minted = await mintInstallationToken(appCreds);
        return minted.token;
      }
      return process.env.GITHUB_TOKEN;
    },
    ensurePullRequest: ensureGitHubPr,
  };
}

// ── Gitea ──────────────────────────────────────────────────────────────────

function createGiteaProvider(): GitProvider {
  return {
    kind: "gitea",
    async resolveToken() {
      // PiAgentRunner._build_env sets GITEA_TOKEN from the per-run scoped
      // service account credentials produced by druppie's gitea_credentials.py.
      return process.env.GITEA_TOKEN;
    },
    ensurePullRequest: ensureGiteaPullRequest,
  };
}

export { parseRemote };

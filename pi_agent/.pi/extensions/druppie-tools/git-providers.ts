/**
 * Git provider abstraction — GitHub App or Gitea, selected at runtime
 * via PI_AGENT_GIT_PROVIDER env var. Uses Node native crypto for JWT
 * signing (no external deps).
 */
import { readFileSync } from "node:fs";
import { createPrivateKey, createSign } from "node:crypto";

import type { GitProvider, GitProviderKind, EnsurePrOptions, EnsurePrResult } from "./types.js";

export { parseRemote };

export function selectGitProvider(explicit?: GitProviderKind): GitProvider {
  const kind: GitProviderKind =
    explicit ?? (process.env.PI_AGENT_GIT_PROVIDER as GitProviderKind) ?? "github_app";
  if (kind === "gitea") return createGiteaProvider();
  if (kind === "github_app") return createGitHubProvider();
  throw new Error(`unknown PI_AGENT_GIT_PROVIDER: ${kind}`);
}

// ── GitHub App ──────────────────────────────────────────────────────────────

interface GitHubAppCredentials {
  appId: string;
  installationId: string;
  privateKey: string;
}

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
    ensurePullRequest: ensureGitHubPullRequest,
  };
}

function loadAppCredentialsFromEnv(): GitHubAppCredentials | null {
  const appId = process.env.GITHUB_APP_ID;
  const installationId = process.env.GITHUB_APP_INSTALLATION_ID;
  const keyPath = process.env.GITHUB_APP_PRIVATE_KEY_PATH;
  if (!appId || !installationId || !keyPath) return null;
  return { appId, installationId, privateKey: keyPath };
}

async function mintInstallationToken(creds: GitHubAppCredentials): Promise<{ token: string }> {
  const pem = creds.privateKey.trimStart().startsWith("-----BEGIN")
    ? creds.privateKey
    : readFileSync(creds.privateKey, "utf-8");
  const jwt = signAppJwt(creds.appId, pem);
  const res = await fetch(
    `https://api.github.com/app/installations/${encodeURIComponent(creds.installationId)}/access_tokens`,
    {
      method: "POST",
      headers: {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${jwt}`,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "oneshot-tdd-agent",
      },
    },
  );
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`GitHub App token mint failed ${res.status}: ${text}`);
  }
  const json = (await res.json()) as { token: string };
  return { token: json.token };
}

function signAppJwt(appId: string, privateKeyPem: string): string {
  const now = Math.floor(Date.now() / 1000);
  const header = { alg: "RS256", typ: "JWT" };
  const payload = { iat: now - 60, exp: now + 9 * 60, iss: appId };
  const b64h = b64url(JSON.stringify(header));
  const b64p = b64url(JSON.stringify(payload));
  const signingInput = `${b64h}.${b64p}`;
  const key = createPrivateKey(privateKeyPem);
  const signer = createSign("RSA-SHA256");
  signer.update(signingInput);
  signer.end();
  const signature = signer.sign(key);
  const b64s = signature.toString("base64url");
  return `${signingInput}.${b64s}`;
}

function b64url(s: string): string {
  return Buffer.from(s, "utf-8").toString("base64url");
}

async function ensureGitHubPullRequest(opts: EnsurePrOptions): Promise<EnsurePrResult> {
  const { owner, repo } = parseRemote(opts.remoteUrl);
  const headParam = `${owner}:${opts.head}`;

  const listUrl = `https://api.github.com/repos/${owner}/${repo}/pulls?state=open&head=${encodeURIComponent(headParam)}&base=${encodeURIComponent(opts.base)}`;
  const listRes = await fetch(listUrl, { headers: ghHeaders(opts.token) });
  if (!listRes.ok) {
    return { action: "skipped", message: `GET pulls ${listRes.status}: ${await listRes.text()}` };
  }
  const existing = (await listRes.json()) as Array<{ number: number; html_url: string }>;
  if (existing.length > 0) {
    return { action: "exists", number: existing[0].number, url: existing[0].html_url };
  }

  const createRes = await fetch(`https://api.github.com/repos/${owner}/${repo}/pulls`, {
    method: "POST",
    headers: { ...ghHeaders(opts.token), "Content-Type": "application/json" },
    body: JSON.stringify({ title: opts.title, body: opts.body, head: opts.head, base: opts.base }),
  });
  if (!createRes.ok) {
    return { action: "skipped", message: `POST pulls ${createRes.status}: ${await createRes.text()}` };
  }
  const created = (await createRes.json()) as { number: number; html_url: string };
  return { action: "created", number: created.number, url: created.html_url };
}

function ghHeaders(token: string): Record<string, string> {
  return {
    Accept: "application/vnd.github+json",
    Authorization: `Bearer ${token}`,
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "oneshot-tdd-agent",
  };
}

// ── Gitea ───────────────────────────────────────────────────────────────────

function createGiteaProvider(): GitProvider {
  return {
    kind: "gitea",
    async resolveToken() {
      return process.env.GITEA_TOKEN;
    },
    ensurePullRequest: ensureGiteaPullRequest,
  };
}

function giteaApiBase(): string {
  const base = process.env.GITEA_BASE_URL || process.env.GITEA_INTERNAL_URL;
  if (!base) throw new Error("GITEA_BASE_URL not set — cannot talk to Gitea API");
  return base.replace(/\/+$/, "") + "/api/v1";
}

function giteaHeaders(token: string): Record<string, string> {
  return {
    Accept: "application/json",
    Authorization: `token ${token}`,
    "User-Agent": "oneshot-tdd-agent",
  };
}

async function ensureGiteaPullRequest(opts: EnsurePrOptions): Promise<EnsurePrResult> {
  const { owner, repo } = parseRemote(opts.remoteUrl);
  const api = giteaApiBase();

  const listUrl =
    `${api}/repos/${owner}/${repo}/pulls?state=open` +
    `&head=${encodeURIComponent(opts.head)}` +
    `&base=${encodeURIComponent(opts.base)}`;
  const listRes = await fetch(listUrl, { headers: giteaHeaders(opts.token) });
  if (!listRes.ok) {
    return { action: "skipped", message: `GET pulls ${listRes.status}: ${await listRes.text()}` };
  }
  const existing = (await listRes.json()) as Array<{ number: number; html_url: string }>;
  if (existing.length > 0) {
    return { action: "exists", number: existing[0].number, url: existing[0].html_url };
  }

  const createRes = await fetch(`${api}/repos/${owner}/${repo}/pulls`, {
    method: "POST",
    headers: { ...giteaHeaders(opts.token), "Content-Type": "application/json" },
    body: JSON.stringify({ title: opts.title, body: opts.body, head: opts.head, base: opts.base }),
  });
  if (!createRes.ok) {
    return { action: "skipped", message: `POST pulls ${createRes.status}: ${await createRes.text()}` };
  }
  const created = (await createRes.json()) as { number: number; html_url: string };
  return { action: "created", number: created.number, url: created.html_url };
}

// ── Shared ──────────────────────────────────────────────────────────────────

function parseRemote(remoteUrl: string): { owner: string; repo: string } {
  let m = remoteUrl.match(/^https?:\/\/[^/]+\/([^/]+)\/([^/]+?)(\.git)?\/?$/);
  if (!m) m = remoteUrl.match(/^git@[^:]+:([^/]+)\/([^/]+?)(\.git)?$/);
  if (!m) throw new Error(`unrecognised remote URL: ${remoteUrl}`);
  return { owner: m[1], repo: m[2] };
}

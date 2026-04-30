/**
 * GitHub App installation-token minting.
 *
 * Flow:
 *   1. Sign a short-lived JWT (<=10min) with the App's RSA private key (RS256)
 *      — GitHub accepts this as proof that you are the App.
 *   2. POST /app/installations/:id/access_tokens → returns a ~1-hour "ghs_..."
 *      installation token scoped to the single installation (i.e. to the repos
 *      the App was installed on).
 *
 * The installation token is what we hand to the push-sandbox and to the PR
 * ensure step. It behaves like a fine-grained PAT but is minted fresh each
 * run and expires quickly, which is exactly what we want.
 *
 * No external deps — node:crypto has everything.
 */
import { readFileSync } from "node:fs";
import { createPrivateKey, createSign } from "node:crypto";

export interface GitHubAppCredentials {
  appId: string;
  installationId: string;
  /** Either the PEM string or a filesystem path to the .pem file. */
  privateKey: string;
}

export interface InstallationToken {
  token: string;
  expiresAt: string; // ISO-8601
}

/**
 * Read App credentials from env. Returns null if any required var is missing.
 * Mirrors the druppie-fork / druppie convention:
 *   GITHUB_APP_ID
 *   GITHUB_APP_INSTALLATION_ID
 *   GITHUB_APP_PRIVATE_KEY_PATH
 */
export function loadAppCredentialsFromEnv(): GitHubAppCredentials | null {
  const appId = process.env.GITHUB_APP_ID;
  const installationId = process.env.GITHUB_APP_INSTALLATION_ID;
  const keyPath = process.env.GITHUB_APP_PRIVATE_KEY_PATH;
  if (!appId || !installationId || !keyPath) return null;
  return { appId, installationId, privateKey: keyPath };
}

export async function mintInstallationToken(
  creds: GitHubAppCredentials,
): Promise<InstallationToken> {
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
  const json = (await res.json()) as { token: string; expires_at: string };
  return { token: json.token, expiresAt: json.expires_at };
}

// ── JWT (RS256) ───────────────────────────────────────────────────────────

/**
 * Sign a short-lived (9-minute) App JWT per GitHub docs.
 * https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-json-web-token-jwt-for-a-github-app
 */
function signAppJwt(appId: string, privateKeyPem: string): string {
  const now = Math.floor(Date.now() / 1000);
  // GitHub requires iat <= now-60s to account for clock drift, and exp <= iat+600s
  const header = { alg: "RS256", typ: "JWT" };
  const payload = {
    iat: now - 60,
    exp: now + 9 * 60,
    iss: appId,
  };
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

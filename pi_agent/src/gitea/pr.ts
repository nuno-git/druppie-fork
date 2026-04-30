/**
 * Gitea PR helpers — mirror of pi_agent/src/github/pr.ts for Gitea.
 *
 * Gitea's REST v1 mirrors the GitHub shape for pulls closely enough that the
 * contract (EnsurePrOptions / EnsurePrResult) is identical. Two differences
 * worth noting:
 *
 *   - Auth header format is `Authorization: token <token>` (not `Bearer …`).
 *   - `head` filter does NOT take the `owner:branch` form — just the branch
 *     name, since Gitea pulls list is already scoped to the target repo.
 *
 * Base URL is taken from GITEA_BASE_URL (set by PiAgentRunner._build_env from
 * GITEA_INTERNAL_URL). The remoteUrl's host is ignored for API calls; only
 * owner/repo are parsed out of it.
 */
import type { EnsurePrOptions, EnsurePrResult } from "../github/pr.js";
import { parseRemote } from "../github/pr.js";

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

export async function ensureGiteaPullRequest(opts: EnsurePrOptions): Promise<EnsurePrResult> {
  const { owner, repo } = parseRemote(opts.remoteUrl);
  const api = giteaApiBase();

  // 1. Already an open PR head → base?
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

  // 2. Create it
  const createRes = await fetch(`${api}/repos/${owner}/${repo}/pulls`, {
    method: "POST",
    headers: { ...giteaHeaders(opts.token), "Content-Type": "application/json" },
    body: JSON.stringify({
      title: opts.title,
      body: opts.body,
      head: opts.head,
      base: opts.base,
    }),
  });
  if (!createRes.ok) {
    return { action: "skipped", message: `POST pulls ${createRes.status}: ${await createRes.text()}` };
  }
  const created = (await createRes.json()) as { number: number; html_url: string };
  return { action: "created", number: created.number, url: created.html_url };
}

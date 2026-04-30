/**
 * GitHub PR helpers — idempotent "ensure a PR exists from head → base."
 *
 * Called on the host after a successful bundle+push, using the same token
 * that went to the push-sandbox. We deliberately keep this out of the
 * push-sandbox container: adding jq + API wrangling there would bloat the
 * tiny alpine+git image, and the token already exists on the host.
 *
 * If you later want agents to autonomously interact with GitHub during a
 * run, promote this to the github-api-proxy pattern druppie uses.
 */

export interface EnsurePrOptions {
  /** https://github.com/org/repo or git@github.com:org/repo.git (both supported) */
  remoteUrl: string;
  /** Branch the agent just pushed. */
  head: string;
  /** Branch to merge into. e.g. "dev", "main". */
  base: string;
  /** Fine-grained PAT or App installation token with Pull requests:write. */
  token: string;
  title: string;
  body: string;
}

export interface EnsurePrResult {
  action: "created" | "exists" | "skipped";
  url?: string;
  number?: number;
  message?: string;
}

export async function ensurePullRequest(opts: EnsurePrOptions): Promise<EnsurePrResult> {
  const { owner, repo } = parseRemote(opts.remoteUrl);
  const headParam = `${owner}:${opts.head}`;

  // 1. Is there already an open PR head → base?
  const listUrl = `https://api.github.com/repos/${owner}/${repo}/pulls?state=open&head=${encodeURIComponent(headParam)}&base=${encodeURIComponent(opts.base)}`;
  const listRes = await fetch(listUrl, { headers: ghHeaders(opts.token) });
  if (!listRes.ok) {
    return { action: "skipped", message: `GET pulls ${listRes.status}: ${await listRes.text()}` };
  }
  const existing = (await listRes.json()) as Array<{ number: number; html_url: string }>;
  if (existing.length > 0) {
    return { action: "exists", number: existing[0].number, url: existing[0].html_url };
  }

  // 2. Create it
  const createRes = await fetch(`https://api.github.com/repos/${owner}/${repo}/pulls`, {
    method: "POST",
    headers: { ...ghHeaders(opts.token), "Content-Type": "application/json" },
    body: JSON.stringify({
      title: opts.title,
      body: opts.body,
      head: opts.head,
      base: opts.base,
    }),
  });

  if (!createRes.ok) {
    const text = await createRes.text();
    return { action: "skipped", message: `POST pulls ${createRes.status}: ${text}` };
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

/**
 * Accept either https://github.com/OWNER/REPO(.git)? or git@github.com:OWNER/REPO(.git)?
 */
export function parseRemote(remoteUrl: string): { owner: string; repo: string } {
  let m = remoteUrl.match(/^https?:\/\/[^/]+\/([^/]+)\/([^/]+?)(\.git)?\/?$/);
  if (!m) m = remoteUrl.match(/^git@[^:]+:([^/]+)\/([^/]+?)(\.git)?$/);
  if (!m) throw new Error(`unrecognised remote URL: ${remoteUrl}`);
  return { owner: m[1], repo: m[2] };
}

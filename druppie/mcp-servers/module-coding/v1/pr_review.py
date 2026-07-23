"""PR review — dedup, diff and sticky review comment for a fixed repo allowlist.

Self-contained: Gitea REST client + review logic in one file, consumed by the
three PR-review tools in tools.py. The Gitea instance, token and repo
allowlist come from server configuration (PRREVIEW_*, falling back to the
module's EXTERNAL_GITEA_* for URL/token) and are never tool arguments, so an
agent cannot review or comment outside them.

Review state is stored IN Gitea itself: each reviewed PR carries exactly one
"sticky" review comment whose body starts with a machine-readable marker
(``<!-- druppie-pr-review sha:<head_sha> verdict:<verdict> -->``). A PR needs
review only when its head SHA differs from the marker SHA — the dedup decision
is made here in code, not by the LLM, and reviews never stack: posting again
edits the same comment. Only marker comments authored by the token's own user
count as sticky: a human quoting the review copies the marker into their
reply, and trusting that copy would make dedup read the wrong SHA and
post_pr_review try to edit a human's comment.

TLS: verification is always on. For instances with a private CA, point
PRREVIEW_SSL_CA_BUNDLE at the CA file — there is no insecure off-switch.
"""

import logging
import os
import re

import httpx

logger = logging.getLogger("coding-mcp")

REQUEST_TIMEOUT = 30.0

# Same default as tools.py's EXTERNAL_GITEA_URL: the coding module targets the
# shared external Gitea (aigit) unless explicitly overridden. Keeping the
# fallback here means the config gate matches the module's actual default, so
# in practice only PRREVIEW_REPOS must be set (see PrReviewModule.__init__).
DEFAULT_EXTERNAL_GITEA_URL = "https://aigit.waterschap.org"

MARKER_RE = re.compile(
    r"<!-- druppie-pr-review sha:([0-9a-fA-F]{7,64}) verdict:([A-Z_]+) -->"
)
SHA_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")

# SKIPPED_TOO_LARGE marks an oversized PR as "reviewed" so the cron does not
# retry (and re-pay for) it every run — the comment tells the author to split.
VALID_VERDICTS = {"APPROVE", "REQUEST_CHANGES", "COMMENT", "SKIPPED_TOO_LARGE"}


def build_marker(sha: str, verdict: str) -> str:
    return f"<!-- druppie-pr-review sha:{sha} verdict:{verdict} -->"


def parse_marker(body: str | None) -> tuple[str, str] | None:
    """Extract (sha, verdict) from a sticky comment body, or None."""
    match = MARKER_RE.search(body or "")
    return (match.group(1), match.group(2)) if match else None


class GiteaPRClient:
    """REST client bound to a single Gitea instance."""

    def __init__(self, base_url: str, token: str, ca_bundle: str | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        # httpx `verify`: True (system CAs) or a path to a private CA bundle.
        self._verify = ca_bundle if ca_bundle else True

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"token {self._token}"}

    @staticmethod
    def _raise_for_status(resp: httpx.Response) -> None:
        if resp.is_success:
            return
        body = resp.text[:2000]
        raise httpx.HTTPStatusError(
            f"{resp.status_code} {resp.reason_phrase} for url '{resp.url}'\n{body}",
            request=resp.request,
            response=resp,
        )

    async def _get(self, path: str, params: dict | None = None, *, raw: bool = False):
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, verify=self._verify) as client:
            resp = await client.get(
                f"{self._base_url}/api/v1/{path}",
                params=params,
                headers=self._headers(),
            )
            self._raise_for_status(resp)
            return resp.text if raw else resp.json()

    async def _post(self, path: str, json_body: dict) -> dict:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, verify=self._verify) as client:
            resp = await client.post(
                f"{self._base_url}/api/v1/{path}",
                json=json_body,
                headers=self._headers(),
            )
            self._raise_for_status(resp)
            return resp.json()

    async def _patch(self, path: str, json_body: dict) -> dict:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, verify=self._verify) as client:
            resp = await client.patch(
                f"{self._base_url}/api/v1/{path}",
                json=json_body,
                headers=self._headers(),
            )
            self._raise_for_status(resp)
            return resp.json()

    async def get_authenticated_user(self) -> dict:
        """Return the user the token belongs to (GET /user)."""
        return await self._get("user")

    async def list_open_pulls(self, owner: str, repo: str, limit: int = 50) -> list[dict]:
        """List open pull requests for a repository."""
        return await self._get(
            f"repos/{owner}/{repo}/pulls",
            {"state": "open", "limit": limit},
        )

    async def get_pull_diff(self, owner: str, repo: str, index: int) -> str:
        """Fetch the unified diff of a pull request (base...head)."""
        return await self._get(f"repos/{owner}/{repo}/pulls/{index}.diff", raw=True)

    async def list_issue_comments(self, owner: str, repo: str, index: int) -> list[dict]:
        """List comments on a PR (Gitea PR comments live on the issue API)."""
        return await self._get(f"repos/{owner}/{repo}/issues/{index}/comments")

    async def create_issue_comment(self, owner: str, repo: str, index: int, body: str) -> dict:
        """Create a comment on a PR."""
        return await self._post(
            f"repos/{owner}/{repo}/issues/{index}/comments", {"body": body}
        )

    async def edit_issue_comment(self, owner: str, repo: str, comment_id: int, body: str) -> dict:
        """Edit an existing PR comment by its comment id."""
        return await self._patch(
            f"repos/{owner}/{repo}/issues/comments/{comment_id}", {"body": body}
        )


class PrReviewModule:
    """High-level PR review operations for the configured repos.

    Cheap to construct (env reads only) — tools.py builds one per tool call,
    so the coding module keeps no PR-review state and starts fine when the
    feature is unconfigured: the ValueError surfaces per call, not at import.
    """

    def __init__(self) -> None:
        # URL and token default to the coding module's external Gitea config,
        # so in most deployments only PRREVIEW_REPOS needs to be set.
        base_url = (
            os.getenv("PRREVIEW_GITEA_URL", "").strip()
            or os.getenv("EXTERNAL_GITEA_URL", "").strip()
            or DEFAULT_EXTERNAL_GITEA_URL
        )
        token = (
            os.getenv("PRREVIEW_GITEA_TOKEN", "").strip()
            or os.getenv("EXTERNAL_GITEA_TOKEN", "").strip()
        )
        repos_raw = os.getenv("PRREVIEW_REPOS", "").strip()

        missing = [
            name
            for name, val in [
                ("PRREVIEW_GITEA_URL (or EXTERNAL_GITEA_URL)", base_url),
                ("PRREVIEW_GITEA_TOKEN (or EXTERNAL_GITEA_TOKEN)", token),
                ("PRREVIEW_REPOS", repos_raw),
            ]
            if not val
        ]
        if missing:
            raise ValueError(
                "PR review is not configured; missing env vars: "
                + ", ".join(missing)
            )

        self._repos = [r.strip() for r in repos_raw.split(",") if r.strip()]
        for repo in self._repos:
            if repo.count("/") != 1:
                raise ValueError(
                    f"PRREVIEW_REPOS entry '{repo}' must be '<owner>/<repo>'"
                )

        self._max_prs_per_run = int(os.getenv("PRREVIEW_MAX_PRS_PER_RUN", "5"))
        self._max_diff_lines = int(os.getenv("PRREVIEW_MAX_DIFF_LINES", "3000"))
        ca_bundle = os.getenv("PRREVIEW_SSL_CA_BUNDLE", "").strip()
        self._client = GiteaPRClient(base_url, token, ca_bundle=ca_bundle or None)
        self._bot_login: str | None = None

    @property
    def repos(self) -> list[str]:
        return list(self._repos)

    def _split_repo(self, repo: str) -> tuple[str, str]:
        """Validate a repo against the allowlist and split into (owner, name)."""
        if repo not in self._repos:
            raise ValueError(
                f"repo '{repo}' is not in the configured allowlist ({', '.join(self._repos)})"
            )
        owner, name = repo.split("/", 1)
        return owner, name

    async def _bot_user_login(self) -> str:
        """Login of the token's own user, fetched once per instance."""
        if self._bot_login is None:
            user = await self._client.get_authenticated_user()
            login = (user or {}).get("login")
            if not login:
                raise ValueError(
                    "could not determine the review bot user (GET /user returned no login)"
                )
            self._bot_login = login
        return self._bot_login

    async def _find_sticky_comment(
        self, owner: str, name: str, index: int
    ) -> tuple[dict | None, tuple[str, str] | None]:
        """Return (comment, (sha, verdict)) for the newest marker comment BY THE BOT.

        Comments by other users are never sticky, even when they contain the
        marker (e.g. a human quote-replying the review) — see module docstring.
        """
        bot_login = await self._bot_user_login()
        comments = await self._client.list_issue_comments(owner, name, index)
        for comment in reversed(comments):
            if (comment.get("user") or {}).get("login") != bot_login:
                continue
            parsed = parse_marker(comment.get("body"))
            if parsed:
                return comment, parsed
        return None, None

    async def list_prs_needing_review(self) -> dict:
        """List open PRs whose head SHA differs from the last-reviewed SHA."""
        needing: list[dict] = []
        skipped_unchanged = 0
        skipped_drafts = 0
        errors: list[str] = []

        for repo in self._repos:
            owner, name = repo.split("/", 1)
            try:
                pulls = await self._client.list_open_pulls(owner, name)
                for pull in pulls:
                    if pull.get("draft"):
                        skipped_drafts += 1
                        continue
                    index = pull.get("number")
                    head_sha = (pull.get("head") or {}).get("sha")
                    if not head_sha:
                        # Without a head SHA the review can never be marked
                        # done (post_pr_review requires it) — skip, not loop.
                        logger.warning("PR %s#%s has no head SHA; skipping", repo, index)
                        continue
                    _, parsed = await self._find_sticky_comment(owner, name, index)
                    previously_reviewed_sha = parsed[0] if parsed else None
                    if previously_reviewed_sha and head_sha == previously_reviewed_sha:
                        skipped_unchanged += 1
                        continue
                    needing.append({
                        "repo": repo,
                        "number": index,
                        "title": pull.get("title"),
                        "author": (pull.get("user") or {}).get("login"),
                        "base_branch": (pull.get("base") or {}).get("ref"),
                        "head_branch": (pull.get("head") or {}).get("ref"),
                        "head_sha": head_sha,
                        "previously_reviewed_sha": previously_reviewed_sha,
                        "url": pull.get("html_url"),
                    })
            except Exception as exc:
                logger.warning("list_prs_needing_review failed for %s: %s", repo, exc)
                errors.append(f"{repo}: {exc}")

        capped = needing[: self._max_prs_per_run]
        result = {
            "success": True,
            "prs": capped,
            "total_needing_review": len(needing),
            "skipped_over_cap": max(0, len(needing) - self._max_prs_per_run),
            "skipped_unchanged": skipped_unchanged,
            "skipped_drafts": skipped_drafts,
        }
        if errors:
            result["errors"] = errors
        return result

    async def get_pr_diff(self, repo: str, pr_number: int) -> dict:
        """Fetch the full PR diff, guarded by the configured size limit."""
        try:
            owner, name = self._split_repo(repo)
            diff = await self._client.get_pull_diff(owner, name, pr_number)
            diff_lines = len(diff.splitlines())
            if diff_lines > self._max_diff_lines:
                return {
                    "success": True,
                    "too_large": True,
                    "diff": None,
                    "diff_lines": diff_lines,
                    "max_diff_lines": self._max_diff_lines,
                    "message": (
                        f"Diff has {diff_lines} lines, over the {self._max_diff_lines}-line "
                        "review limit. Post a SKIPPED_TOO_LARGE review asking the author "
                        "to split the PR, so it is not retried every run."
                    ),
                }
            return {
                "success": True,
                "too_large": False,
                "diff": diff,
                "diff_lines": diff_lines,
                "max_diff_lines": self._max_diff_lines,
            }
        except Exception as exc:
            logger.warning("get_pr_diff(%s#%s) failed: %s", repo, pr_number, exc)
            return {"success": False, "error": str(exc)}

    async def post_pr_review(
        self, repo: str, pr_number: int, head_sha: str, verdict: str, body: str
    ) -> dict:
        """Create or update the single sticky review comment on a PR.

        Embeds the reviewed head SHA in the marker, so posting the review and
        marking the PR as reviewed are one atomic step.
        """
        try:
            owner, name = self._split_repo(repo)
            if verdict not in VALID_VERDICTS:
                return {
                    "success": False,
                    "error": f"Invalid verdict '{verdict}'. "
                             f"Valid verdicts: {', '.join(sorted(VALID_VERDICTS))}",
                }
            if not SHA_RE.match(head_sha or ""):
                return {
                    "success": False,
                    "error": "head_sha must be the commit SHA from list_prs_needing_review",
                }
            if not (body or "").strip():
                return {"success": False, "error": "body must be non-empty"}

            comment_body = (
                f"{build_marker(head_sha, verdict)}\n\n"
                f"## Druppie PR review — {verdict}\n"
                f"_Reviewed commit `{head_sha[:10]}` (automated scheduled review)._\n\n"
                f"{body.strip()}\n"
            )

            sticky, _ = await self._find_sticky_comment(owner, name, pr_number)
            if sticky:
                result = await self._client.edit_issue_comment(
                    owner, name, sticky["id"], comment_body
                )
                action = "updated"
            else:
                result = await self._client.create_issue_comment(
                    owner, name, pr_number, comment_body
                )
                action = "created"

            return {
                "success": True,
                "action": action,
                "repo": repo,
                "pr_number": pr_number,
                "verdict": verdict,
                "reviewed_sha": head_sha,
                "comment_id": result.get("id"),
                "comment_url": result.get("html_url"),
            }
        except Exception as exc:
            logger.warning("post_pr_review(%s#%s) failed: %s", repo, pr_number, exc)
            return {"success": False, "error": str(exc)}

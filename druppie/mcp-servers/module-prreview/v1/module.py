"""PR review module — dedup, diff and sticky review comment for fixed repos.

Reads the Gitea URL, token and repo allowlist from the environment, builds a
GiteaPRClient, and exposes the high-level operations consumed by the MCP tools.
The repo allowlist is fixed here; every operation validates its repo argument
against it, so an agent can never review or comment outside the allowlist.

Review state is stored IN Gitea itself: each reviewed PR carries exactly one
"sticky" review comment whose body starts with a machine-readable marker
(``<!-- druppie-pr-review sha:<head_sha> verdict:<verdict> -->``). A PR needs
review only when its head SHA differs from the marker SHA — the dedup decision
is made here in code, not by the LLM, and reviews never stack: posting again
edits the same comment.
"""

import logging
import os
import re

from .client import GiteaPRClient

logger = logging.getLogger("prreview-mcp")

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


class PrReviewModule:
    """High-level PR review operations for the configured repos."""

    def __init__(self) -> None:
        base_url = os.getenv("PRREVIEW_GITEA_URL", "").strip()
        token = os.getenv("PRREVIEW_GITEA_TOKEN", "").strip()
        repos_raw = os.getenv("PRREVIEW_REPOS", "").strip()

        missing = [
            name
            for name, val in [
                ("PRREVIEW_GITEA_URL", base_url),
                ("PRREVIEW_GITEA_TOKEN", token),
                ("PRREVIEW_REPOS", repos_raw),
            ]
            if not val
        ]
        if missing:
            raise ValueError(
                "PR review MCP is misconfigured; missing env vars: "
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
        logger.info("PR review MCP bound to repos: %s", ", ".join(self._repos))

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

    async def _find_sticky_comment(
        self, owner: str, name: str, index: int
    ) -> tuple[dict | None, tuple[str, str] | None]:
        """Return (comment, (sha, verdict)) for the newest marker comment, if any."""
        comments = await self._client.list_issue_comments(owner, name, index)
        for comment in reversed(comments):
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

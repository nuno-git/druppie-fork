"""PR review v1 — MCP Tool Definitions.

Reviews pull requests on a fixed allowlist of Gitea repositories. The Gitea
instance and the allowlist are set by server configuration (PRREVIEW_*) and are
never tool arguments, so an agent cannot review or comment outside them.

Which PRs need review is decided server-side by comparing each PR's head SHA
against the marker in its sticky review comment — the agent only ever sees PRs
that actually changed since the last review, and posting a review updates the
one sticky comment instead of stacking new ones.
"""

import logging

from fastmcp import FastMCP

from .module import PrReviewModule

logger = logging.getLogger("prreview-mcp")

MODULE_ID = "prreview"
MODULE_VERSION = "1.0.0"

mcp = FastMCP(
    "PR Review v1",
    version=MODULE_VERSION,
    instructions=(
        "Review pull requests on a pre-configured allowlist of Gitea "
        "repositories. list_prs_needing_review already filters out unchanged, "
        "draft and over-cap PRs — review exactly the PRs it returns, fetch "
        "each diff with get_pr_diff, and publish with post_pr_review."
    ),
)

module = PrReviewModule()


@mcp.tool()
async def list_prs_needing_review() -> dict:
    """List open PRs that changed since their last review (deduped server-side).

    A PR needs review when its head commit differs from the SHA recorded in its
    sticky review comment. Draft PRs and unchanged PRs are skipped; the result
    is capped per run (skipped_over_cap tells you how many wait for next run).

    Returns:
        Dict with prs (repo, number, title, author, base_branch, head_branch,
        head_sha, previously_reviewed_sha, url), total_needing_review,
        skipped_over_cap, skipped_unchanged and skipped_drafts counts.
    """
    return await module.list_prs_needing_review()


@mcp.tool()
async def get_pr_diff(repo: str, pr_number: int) -> dict:
    """Fetch the unified diff of a PR (base...head), size-guarded.

    Args:
        repo: '<owner>/<repo>' — must come from list_prs_needing_review.
        pr_number: The PR number to fetch.

    Returns:
        Dict with diff (unified diff text) and diff_lines. When the diff is
        over the size limit, too_large is true and diff is null — post a
        SKIPPED_TOO_LARGE review instead of reviewing.
    """
    return await module.get_pr_diff(repo, pr_number)


@mcp.tool()
async def post_pr_review(
    repo: str, pr_number: int, head_sha: str, verdict: str, body: str
) -> dict:
    """Publish the review as the PR's single sticky comment (create or update).

    Posting also marks the PR as reviewed at head_sha, so it will not be
    reviewed again until new commits are pushed. Reviews never stack — an
    existing sticky comment is edited in place.

    Args:
        repo: '<owner>/<repo>' — must come from list_prs_needing_review.
        pr_number: The PR number to review.
        head_sha: The head_sha value from list_prs_needing_review (records
            exactly which commit was reviewed).
        verdict: One of APPROVE, REQUEST_CHANGES, COMMENT, SKIPPED_TOO_LARGE.
        body: The review body in Markdown (findings with severities, or a
            one-line approval).

    Returns:
        Dict with action (created/updated), comment_id and comment_url.
    """
    return await module.post_pr_review(repo, pr_number, head_sha, verdict, body)

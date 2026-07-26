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

import asyncio
import logging
import os
import random
import re

import httpx

logger = logging.getLogger("coding-mcp")

REQUEST_TIMEOUT = 30.0

# Connection robustness: the reviewer runs unattended on a cron against a Gitea
# that may briefly 5xx (restart/upgrade), rate-limit (429) or drop a connection.
# Transient failures are retried with exponential backoff + jitter so a blip
# does not cost a whole review round; non-transient errors (4xx, TLS trust)
# still surface once the attempts are spent. Tunable via PRREVIEW_HTTP_ATTEMPTS.
DEFAULT_HTTP_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 0.5
BACKOFF_MAX_SECONDS = 8.0
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

# Gitea list endpoints paginate (max 50 per page). The reviewer must see EVERY
# open PR and EVERY comment on a PR: a missing page would silently drop PRs from
# review and — worse — hide the bot's own sticky comment, so dedup would
# re-review and post_pr_review would stack a second comment. List calls page to
# the end, bounded by MAX_PAGES as a runaway guard (logged if ever hit).
GITEA_PAGE_LIMIT = 50
MAX_PAGES = 40

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


def _env_int(name: str, default: int) -> int:
    """Parse an int env var, falling back to `default` on unset/blank/garbage.

    A bad override (e.g. an empty string from an unquoted Helm value) must not
    crash module construction — that would masquerade as "PR review is not
    configured" and hide the real cause.
    """
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        logger.warning("invalid %s=%r; using default %d", name, raw, default)
        return default


def build_marker(sha: str, verdict: str) -> str:
    return f"<!-- druppie-pr-review sha:{sha} verdict:{verdict} -->"


def parse_marker(body: str | None) -> tuple[str, str] | None:
    """Extract (sha, verdict) from a sticky comment body, or None."""
    match = MARKER_RE.search(body or "")
    return (match.group(1), match.group(2)) if match else None


_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def diff_new_line_positions(diff: str) -> dict[str, set[int]]:
    """Map each file in a unified diff to the NEW-file line numbers that can
    carry an inline review comment.

    Gitea attaches an inline comment only when its ``new_position`` is a line
    the diff actually shows on the new side — an added ('+') or context (' ')
    line inside a hunk. A ``new_position`` outside every hunk makes Gitea
    reject the whole review, so post_pr_review validates every requested line
    against this map and diverts the misses to the summary instead.

    The path is taken from the ``+++ b/<path>`` header; a pure deletion whose
    new side is ``/dev/null`` contributes no attachable lines.
    """
    positions: dict[str, set[int]] = {}
    current: str | None = None
    new_ln = 0
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            target = raw[4:].strip()
            if target == "/dev/null":
                current = None
            else:
                # strip the "b/" (or "a/") prefix git prepends
                current = target[2:] if target[:2] in ("b/", "a/") else target
                positions.setdefault(current, set())
            continue
        if raw.startswith("@@"):
            m = _HUNK_RE.match(raw)
            if m:
                new_ln = int(m.group(1))
            continue
        if current is None:
            continue
        if raw.startswith("+"):
            positions[current].add(new_ln)
            new_ln += 1
        elif raw.startswith("-"):
            # old side only — does not advance the new-file line counter
            continue
        elif raw.startswith(" "):
            positions[current].add(new_ln)
            new_ln += 1
    return positions


INLINE_SNAP_DISTANCE = 8


def plan_inline_comments(
    findings: list[dict],
    positions: dict[str, set[int]],
    max_inline: int,
    snap: int = INLINE_SNAP_DISTANCE,
) -> tuple[list[dict], list[dict]]:
    """Split findings into Gitea inline comments and a summary overflow list.

    A finding is ``{"path"|"file", "line", "severity", "body", "title"?}``. It
    becomes an inline comment only when its line is a diff-anchorable NEW-file
    line for that file (``positions``); a near miss (<= ``snap`` lines from an
    anchorable line, e.g. the LLM pointed at the declaration rather than the
    changed line) is snapped to the closest one. Everything else — a wrong
    file, a line far outside any hunk, or anything past ``max_inline`` — is
    returned as overflow so the caller can fold it into the summary body
    instead of letting Gitea reject the whole review.

    Returns (inline_comments, overflow_findings). Findings are ordered by
    severity (BLOCKER first) so the cap keeps the most important ones inline.
    """
    order = {"BLOCKER": 0, "MAJOR": 1, "MINOR": 2, "NIT": 3, "QUESTION": 4}
    ranked = sorted(findings, key=lambda f: order.get(f.get("severity", ""), 9))

    inline: list[dict] = []
    overflow: list[dict] = []
    for finding in ranked:
        path = finding.get("path") or finding.get("file")
        line = finding.get("line")
        valid = positions.get(path or "")
        if not path or not valid or line is None:
            overflow.append(finding)
            continue
        anchor = line if line in valid else min(
            valid, key=lambda candidate: abs(candidate - line)
        )
        if anchor not in valid or abs(anchor - line) > snap:
            overflow.append(finding)
            continue
        if len(inline) >= max_inline:
            overflow.append(finding)
            continue
        severity = finding.get("severity", "")
        title = finding.get("title", "")
        header = " — ".join(part for part in (severity, title) if part)
        body = f"**{header}**\n\n{finding.get('body', '')}" if header else finding.get("body", "")
        if anchor != line:
            body += f"\n\n<sub>(anchored near L{line})</sub>"
        inline.append({"path": path, "new_position": anchor, "body": body})
    return inline, overflow


def _render_overflow(overflow: list[dict]) -> str:
    """Render findings that could not be diff-anchored as a summary section."""
    lines = [
        "### Findings not anchored to the diff",
        "_(the referenced line falls outside a changed hunk)_",
        "",
    ]
    for finding in overflow:
        path = finding.get("path") or finding.get("file") or "?"
        loc = f"`{path}:{finding.get('line')}`"
        header = " — ".join(
            part for part in (finding.get("severity", ""), finding.get("title", "")) if part
        )
        lines.append(f"- {loc} {header}".rstrip())
        text = (finding.get("body") or "").strip()
        if text:
            for para in text.splitlines():
                lines.append(f"  > {para}")
    return "\n".join(lines)


class GiteaPRClient:
    """REST client bound to a single Gitea instance."""

    def __init__(
        self,
        base_url: str,
        token: str,
        ca_bundle: str | None = None,
        max_attempts: int = DEFAULT_HTTP_ATTEMPTS,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        # httpx `verify`: True (system CAs) or a path to a private CA bundle.
        self._verify = ca_bundle if ca_bundle else True
        # At least one attempt; retries are on top of the first try.
        self._max_attempts = max(1, max_attempts)

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

    async def _sleep_backoff(self, attempt: int) -> None:
        """Wait before the retry after `attempt` (1-based): exponential + jitter."""
        delay = min(BACKOFF_MAX_SECONDS, BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))
        await asyncio.sleep(delay + random.uniform(0, delay / 2))

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
        raw: bool = False,
    ):
        """Issue one API request, retrying transient failures (transport errors,
        5xx, 429) with backoff. Non-transient responses raise via
        _raise_for_status; the last attempt always propagates its outcome."""
        url = f"{self._base_url}/api/v1/{path}"
        for attempt in range(1, self._max_attempts + 1):
            is_last = attempt == self._max_attempts
            try:
                async with httpx.AsyncClient(
                    timeout=REQUEST_TIMEOUT, verify=self._verify
                ) as client:
                    resp = await client.request(
                        method,
                        url,
                        params=params,
                        json=json_body,
                        headers=self._headers(),
                    )
            except httpx.TransportError as exc:
                # Timeouts, connect resets, protocol errors, TLS failures. Retry
                # the transient ones; a genuine misconfig (e.g. a bad CA bundle)
                # simply fails again and surfaces after the attempts are spent.
                if is_last:
                    raise
                logger.warning(
                    "gitea %s %s transport error %r (attempt %d/%d); retrying",
                    method, path, exc, attempt, self._max_attempts,
                )
                await self._sleep_backoff(attempt)
                continue
            if resp.status_code in RETRYABLE_STATUS and not is_last:
                logger.warning(
                    "gitea %s %s -> %d (attempt %d/%d); retrying",
                    method, path, resp.status_code, attempt, self._max_attempts,
                )
                await self._sleep_backoff(attempt)
                continue
            self._raise_for_status(resp)
            return resp.text if raw else resp.json()

    async def _get(self, path: str, params: dict | None = None, *, raw: bool = False):
        return await self._request("GET", path, params=params, raw=raw)

    async def _get_paginated(self, path: str, params: dict | None = None) -> list[dict]:
        """GET every page of a Gitea list endpoint, concatenated in order.

        Stops at the first short (< GITEA_PAGE_LIMIT) page; bounded by MAX_PAGES
        so a misbehaving endpoint can never loop forever (truncation is logged,
        never silent). Each page goes through _request, so retries apply per page.
        """
        base = dict(params or {})
        base["limit"] = GITEA_PAGE_LIMIT
        items: list[dict] = []
        for page in range(1, MAX_PAGES + 1):
            batch = await self._request("GET", path, params={**base, "page": page})
            if not isinstance(batch, list):
                logger.warning("paginated GET %s returned a non-list; stopping", path)
                break
            items.extend(batch)
            if len(batch) < GITEA_PAGE_LIMIT:
                return items
        logger.warning(
            "paginated GET %s hit MAX_PAGES=%d (%d items); results may be truncated",
            path, MAX_PAGES, len(items),
        )
        return items

    async def _post(self, path: str, json_body: dict) -> dict:
        return await self._request("POST", path, json_body=json_body)

    async def _patch(self, path: str, json_body: dict) -> dict:
        return await self._request("PATCH", path, json_body=json_body)

    async def _delete(self, path: str) -> None:
        # raw=True: a successful DELETE is 204 No Content, so resp.json() would
        # raise on the empty body — take the text and discard it.
        await self._request("DELETE", path, raw=True)

    async def get_authenticated_user(self) -> dict:
        """Return the user the token belongs to (GET /user)."""
        return await self._get("user")

    async def list_open_pulls(self, owner: str, repo: str) -> list[dict]:
        """List ALL open pull requests for a repository (paged to the end)."""
        return await self._get_paginated(
            f"repos/{owner}/{repo}/pulls", {"state": "open"}
        )

    async def get_pull(self, owner: str, repo: str, index: int) -> dict:
        """Fetch a single pull request (GET /repos/{owner}/{repo}/pulls/{index})."""
        return await self._get(f"repos/{owner}/{repo}/pulls/{index}")

    async def get_pull_diff(self, owner: str, repo: str, index: int) -> str:
        """Fetch the unified diff of a pull request (base...head)."""
        return await self._get(f"repos/{owner}/{repo}/pulls/{index}.diff", raw=True)

    async def list_issue_comments(self, owner: str, repo: str, index: int) -> list[dict]:
        """List ALL comments on a PR, paged (Gitea PR comments live on the issue
        API). Full coverage is required for dedup: the sticky review comment may
        sit on any page, and missing it would restack reviews on busy PRs."""
        return await self._get_paginated(f"repos/{owner}/{repo}/issues/{index}/comments")

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

    async def list_pull_reviews(self, owner: str, repo: str, index: int) -> list[dict]:
        """List ALL reviews on a PR (paged). A review carries the inline
        line-anchored comments; issue comments (above) carry the sticky marker."""
        return await self._get_paginated(f"repos/{owner}/{repo}/pulls/{index}/reviews")

    async def delete_pull_review(
        self, owner: str, repo: str, index: int, review_id: int
    ) -> None:
        """Delete a review and its inline comments (used to prevent stacking)."""
        await self._delete(f"repos/{owner}/{repo}/pulls/{index}/reviews/{review_id}")

    async def create_pull_review(
        self,
        owner: str,
        repo: str,
        index: int,
        *,
        commit_id: str,
        event: str,
        body: str,
        comments: list[dict],
    ) -> dict:
        """Create a PR review carrying inline comments.

        ``comments`` is a list of ``{"path", "new_position", "body"}`` dicts;
        ``new_position`` must be a NEW-file line that the diff shows (validated
        by the caller via diff_new_line_positions) or Gitea rejects the whole
        review. ``event`` is one of Gitea's APPROVED / REQUEST_CHANGES /
        COMMENT / PENDING; the reviewer always uses COMMENT so the bot never
        alters the PR's merge/approval state.
        """
        return await self._post(
            f"repos/{owner}/{repo}/pulls/{index}/reviews",
            {
                "commit_id": commit_id,
                "event": event,
                "body": body,
                "comments": comments,
            },
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

        self._max_prs_per_run = _env_int("PRREVIEW_MAX_PRS_PER_RUN", 5)
        self._max_diff_lines = _env_int("PRREVIEW_MAX_DIFF_LINES", 3000)
        # Cap inline comments per review so a pathological run cannot flood a PR
        # with hundreds of anchored notes; the overflow stays in the summary body.
        self._max_inline_comments = _env_int("PRREVIEW_MAX_INLINE_COMMENTS", 30)
        ca_bundle = os.getenv("PRREVIEW_SSL_CA_BUNDLE", "").strip()
        self._client = GiteaPRClient(
            base_url,
            token,
            ca_bundle=ca_bundle or None,
            max_attempts=_env_int("PRREVIEW_HTTP_ATTEMPTS", DEFAULT_HTTP_ATTEMPTS),
        )
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
        repos_ok = 0

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
                repos_ok += 1
            except Exception as exc:
                # Include the exception type: transport failures like a TLS
                # trust error or ConnectTimeout stringify to "", which would
                # otherwise surface as a blank "<repo>: " and read as "no PRs".
                logger.warning(
                    "list_prs_needing_review failed for %s: %r", repo, exc
                )
                errors.append(f"{repo}: {type(exc).__name__}: {exc}")

        capped = needing[: self._max_prs_per_run]
        # success=False only on a TOTAL outage (every configured repo errored),
        # so the agent surfaces "the review round could not run" instead of the
        # indistinguishable-looking "0 PRs need review". A partial failure (some
        # repos listed) stays success=True with the errors attached.
        total_failure = bool(errors) and repos_ok == 0
        result = {
            "success": not total_failure,
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

    async def _delete_prior_bot_reviews(
        self, owner: str, name: str, pr_number: int
    ) -> None:
        """Drop the bot's earlier reviews so inline comments don't accumulate
        across re-review rounds (the issue-comment marker is edited in place,
        but each POST /reviews creates a NEW review — hence the cleanup).

        Must run on EVERY re-review, including one that posts no inline comments
        (e.g. an APPROVE after the author fixed everything) — otherwise a stale
        REQUEST_CHANGES review from an earlier commit would linger and
        contradict the new verdict. Best-effort: a listing or delete failure is
        logged, not raised, so it can never lose the summary/marker.
        """
        bot_login = await self._bot_user_login()
        try:
            existing = await self._client.list_pull_reviews(owner, name, pr_number)
        except Exception as exc:  # non-fatal: worst case is a stale prior review
            logger.warning("list_pull_reviews(%s/%s#%s) failed: %s", owner, name, pr_number, exc)
            return
        for review in existing:
            if (review.get("user") or {}).get("login") == bot_login:
                try:
                    await self._client.delete_pull_review(
                        owner, name, pr_number, review["id"]
                    )
                except Exception as exc:
                    logger.warning(
                        "delete_pull_review(%s/%s#%s id=%s) failed: %s",
                        owner, name, pr_number, review.get("id"), exc,
                    )

    async def _publish_inline_review(
        self, owner: str, name: str, pr_number: int, head_sha: str, findings: list[dict]
    ) -> tuple[int, list[dict]]:
        """Post ``findings`` as one PR review of line-anchored comments.

        Fetches the PR diff to learn which NEW-file lines are anchorable, maps
        the findings with plan_inline_comments, then creates the fresh review.
        The bot's previous reviews are cleared separately by the caller (see
        _delete_prior_bot_reviews) so the cleanup happens even when this round
        yields no inline comments. The event is always COMMENT so the bot never
        changes the PR's merge/approval state; the verdict lives in the sticky
        marker comment. Returns (posted_count, overflow) where overflow is the
        findings that could not be anchored (wrong file / line outside any hunk
        / over the cap) and belong in the summary body instead.
        """
        diff = await self._client.get_pull_diff(owner, name, pr_number)
        positions = diff_new_line_positions(diff)
        inline, overflow = plan_inline_comments(
            findings, positions, self._max_inline_comments
        )
        if not inline:
            return 0, overflow

        await self._client.create_pull_review(
            owner, name, pr_number,
            commit_id=head_sha,
            event="COMMENT",
            body=f"{len(inline)} inline finding(s) — see the sticky summary for the verdict.",
            comments=inline,
        )
        return len(inline), overflow

    async def post_pr_review(
        self,
        repo: str,
        pr_number: int,
        head_sha: str,
        verdict: str,
        body: str,
        comments: list[dict] | None = None,
    ) -> dict:
        """Publish the review: a sticky summary comment plus optional inline notes.

        The sticky issue comment carries the ``sha:<head>`` marker (dedup) and
        the verdict + summary, edited in place so summaries never stack.
        ``comments`` (each ``{"file"/"path", "line", "severity", "title", "body"}``)
        are posted as line-anchored inline comments via a single PR review;
        those that cannot be anchored to the diff are folded into the summary.
        Posting also marks the PR as reviewed at head_sha.
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

            # Cross-validate (pr_number, head_sha) against the live PR before
            # writing anything. The diff/title/body handed to the reviewing LLM
            # are attacker-controlled, so an injected instruction could try to
            # steer post_pr_review at a DIFFERENT PR or forge a marker SHA to
            # poison dedup (making a PR silently skip future reviews). The repo
            # allowlist alone doesn't stop that. This module is stateless (built
            # per call), so the authoritative check is Gitea itself: the PR must
            # exist in the allowlisted repo and head_sha must equal its real,
            # current head. A jailbroken LLM cannot satisfy this for a forged
            # PR/SHA. Fail closed if the PR can't be confirmed.
            try:
                pull = await self._client.get_pull(owner, name, pr_number)
            except Exception as exc:
                logger.warning(
                    "post_pr_review: could not verify %s#%s: %s", repo, pr_number, exc
                )
                return {
                    "success": False,
                    "error": (
                        f"could not verify PR {repo}#{pr_number} against Gitea "
                        f"before posting: {exc}"
                    ),
                }
            actual_head_sha = (pull.get("head") or {}).get("sha") or ""
            if actual_head_sha.lower() != head_sha.lower():
                logger.warning(
                    "post_pr_review: head_sha mismatch for %s#%s (given=%s actual=%s)",
                    repo, pr_number, head_sha, actual_head_sha,
                )
                return {
                    "success": False,
                    "error": (
                        f"head_sha '{head_sha}' does not match the current head "
                        f"'{actual_head_sha}' of {repo}#{pr_number}. Only review the "
                        "exact repo/number/head_sha returned by "
                        "list_prs_needing_review for the PR you are reviewing."
                    ),
                }

            # Clear the bot's prior inline review unconditionally — even a
            # summary-only APPROVE with no findings must wipe an earlier
            # commit's REQUEST_CHANGES inline comments, or they linger and
            # contradict the new verdict. Best-effort (never raises).
            await self._delete_prior_bot_reviews(owner, name, pr_number)

            # Publish inline comments: the overflow (findings that could not be
            # anchored) is appended to the sticky body so nothing is silently
            # dropped. A failure here must not lose the summary/marker.
            inline_posted = 0
            overflow: list[dict] = []
            inline_error: str | None = None
            if comments:
                try:
                    inline_posted, overflow = await self._publish_inline_review(
                        owner, name, pr_number, head_sha, comments
                    )
                except Exception as exc:
                    logger.warning(
                        "inline review for %s#%s failed, falling back to summary only: %s",
                        repo, pr_number, exc,
                    )
                    inline_error = str(exc)
                    overflow = list(comments)

            comment_body = (
                f"{build_marker(head_sha, verdict)}\n\n"
                f"## Druppie PR review — {verdict}\n"
                f"_Reviewed commit `{head_sha[:10]}` (automated scheduled review)._\n\n"
                f"{body.strip()}\n"
            )
            if overflow:
                comment_body += "\n" + _render_overflow(overflow) + "\n"

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
                "inline_comments_posted": inline_posted,
                "inline_comments_overflow": len(overflow),
                "inline_error": inline_error,
            }
        except Exception as exc:
            logger.warning("post_pr_review(%s#%s) failed: %s", repo, pr_number, exc)
            return {"success": False, "error": str(exc)}

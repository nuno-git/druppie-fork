"""Tests for the PR-review tools in module-coding (scheduled PR review).

The feature's guarantees, pinned from two angles:

1. Static (tools.py): module-coding exposes the three review tools, and none
   of them accepts a base URL / token / owner argument that could steer them
   at another Gitea instance or outside the configured repo allowlist.
2. Behavioral (pr_review.py): the dedup decision (head SHA vs sticky-comment
   marker) is made in code; drafts and unchanged PRs are skipped; the per-run
   cap and diff-size guard hold; post_pr_review edits the one sticky comment
   instead of stacking new ones and validates repo/verdict/sha inputs; missing
   configuration raises per instantiation (surfaced per call), never at the
   coding module's import.

The module-server tree (`druppie/mcp-servers/module-coding`) is a standalone
service: `tools.py` needs `fastmcp`, which is NOT installed in the main
druppie test environment. pr_review.py is deliberately self-contained (httpx
only), so we stub httpx and load it by path, mirroring
`test_azuredevops_isolation.py`.
"""

from __future__ import annotations

import ast
import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import pytest

_MOD_DIR = (
    Path(__file__).resolve().parents[1]
    / "mcp-servers"
    / "module-coding"
)
_REPO = "ai/druppie"
_BOT = "druppie-bot"

PR_REVIEW_TOOLS = {
    "list_prs_needing_review",
    "get_pr_diff",
    "post_pr_review",
}


# ---------------------------------------------------------------------------
# Static check — tools.py exposes the review tools, no scope leaks
# ---------------------------------------------------------------------------

def _tool_functions(source_path: Path) -> dict[str, ast.AsyncFunctionDef]:
    """Return {name: node} for every @mcp.tool()-decorated async function."""
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    tools: dict[str, ast.AsyncFunctionDef] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        for dec in node.decorator_list:
            func = dec.func if isinstance(dec, ast.Call) else dec
            if isinstance(func, ast.Attribute) and func.attr == "tool":
                tools[node.name] = node
    return tools


def test_coding_module_exposes_the_pr_review_tools():
    tools = _tool_functions(_MOD_DIR / "v1" / "tools.py")
    assert PR_REVIEW_TOOLS <= set(tools)


def test_no_pr_review_tool_accepts_instance_or_token_arguments():
    tools = _tool_functions(_MOD_DIR / "v1" / "tools.py")
    forbidden = {"base_url", "url", "gitea_url", "token", "owner", "org"}
    for name in PR_REVIEW_TOOLS:
        params = {a.arg for a in tools[name].args.args}
        leaked = params & forbidden
        assert not leaked, f"tool {name} exposes instance/token argument(s): {leaked}"


# ---------------------------------------------------------------------------
# Behavioral checks — pr_review.py
# ---------------------------------------------------------------------------

def _install_dep_stubs() -> None:
    """Provide a minimal stand-in for httpx (not installed here)."""
    if "httpx" not in sys.modules:
        httpx = types.ModuleType("httpx")

        class _AsyncClient:  # pragma: no cover - never used (client is faked)
            def __init__(self, *a, **k):
                ...

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

        class _HTTPStatusError(Exception):
            def __init__(self, message, *, request=None, response=None):
                super().__init__(message)

        httpx.AsyncClient = _AsyncClient
        httpx.HTTPStatusError = _HTTPStatusError
        sys.modules["httpx"] = httpx


def _load_module_under_test(monkeypatch):
    """Load pr_review.py with env + deps stubbed (self-contained module)."""
    _install_dep_stubs()
    for var in ("EXTERNAL_GITEA_URL", "EXTERNAL_GITEA_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("PRREVIEW_GITEA_URL", "https://gitea.example.org")
    monkeypatch.setenv("PRREVIEW_GITEA_TOKEN", "stub-token")
    monkeypatch.setenv("PRREVIEW_REPOS", _REPO)
    monkeypatch.setenv("PRREVIEW_MAX_PRS_PER_RUN", "2")
    monkeypatch.setenv("PRREVIEW_MAX_DIFF_LINES", "10")

    spec = importlib.util.spec_from_file_location(
        "coding_pr_review", _MOD_DIR / "v1" / "pr_review.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["coding_pr_review"] = mod
    spec.loader.exec_module(mod)
    return mod


class _FakeClient:
    """In-memory Gitea: open PRs + comments per (owner/repo, index)."""

    def __init__(self, pulls=None, comments=None):
        self.pulls = pulls or []
        self.comments = comments or {}
        self.created: list[tuple[int, str]] = []
        self.edited: list[tuple[int, str]] = []
        self.diff = ""

    async def get_authenticated_user(self):
        return {"login": _BOT}

    async def list_open_pulls(self, owner, repo, limit=50):
        return self.pulls

    async def get_pull_diff(self, owner, repo, index):
        return self.diff

    async def list_issue_comments(self, owner, repo, index):
        return self.comments.get(index, [])

    async def create_issue_comment(self, owner, repo, index, body):
        self.created.append((index, body))
        return {"id": 1000 + index, "html_url": f"https://x/pr/{index}#c"}

    async def edit_issue_comment(self, owner, repo, comment_id, body):
        self.edited.append((comment_id, body))
        return {"id": comment_id, "html_url": f"https://x/c/{comment_id}"}


def _pull(number, sha, draft=False):
    return {
        "number": number,
        "title": f"PR {number}",
        "draft": draft,
        "user": {"login": "dev"},
        "base": {"ref": "colab-dev"},
        "head": {"ref": f"feat/{number}", "sha": sha},
        "html_url": f"https://x/pr/{number}",
    }


def _sticky(mod, sha, verdict="APPROVE", comment_id=77):
    return {
        "id": comment_id,
        "user": {"login": _BOT},
        "body": mod.build_marker(sha, verdict) + "\n\nold review",
    }


def _human_quote(mod, sha, verdict="APPROVE", comment_id=88):
    """A human reply quoting the bot review — contains the marker verbatim."""
    return {
        "id": comment_id,
        "user": {"login": "some-human"},
        "body": "> " + mod.build_marker(sha, verdict) + "\n\nreplying to the bot",
    }


@pytest.fixture()
def mod(monkeypatch):
    return _load_module_under_test(monkeypatch)


@pytest.fixture()
def module(mod):
    m = mod.PrReviewModule()
    m._client = _FakeClient()
    return m


# --- marker roundtrip -------------------------------------------------------

def test_marker_roundtrip(mod):
    marker = mod.build_marker("abc1234", "REQUEST_CHANGES")
    assert mod.parse_marker(f"{marker}\n\nbody") == ("abc1234", "REQUEST_CHANGES")


def test_parse_marker_ignores_regular_comments(mod):
    assert mod.parse_marker("just a human comment") is None
    assert mod.parse_marker(None) is None
    assert mod.parse_marker("<!-- druppie-pr-review sha:nothex verdict:APPROVE -->") is None


# --- config validation ------------------------------------------------------

def test_missing_repos_raises(mod, monkeypatch):
    monkeypatch.delenv("PRREVIEW_REPOS")
    with pytest.raises(ValueError, match="PRREVIEW_REPOS"):
        mod.PrReviewModule()


def test_missing_token_raises(mod, monkeypatch):
    monkeypatch.delenv("PRREVIEW_GITEA_TOKEN")
    with pytest.raises(ValueError, match="PRREVIEW_GITEA_TOKEN"):
        mod.PrReviewModule()


def test_url_and_token_fall_back_to_external_gitea(mod, monkeypatch):
    monkeypatch.delenv("PRREVIEW_GITEA_URL")
    monkeypatch.delenv("PRREVIEW_GITEA_TOKEN")
    monkeypatch.setenv("EXTERNAL_GITEA_URL", "https://aigit.example.org")
    monkeypatch.setenv("EXTERNAL_GITEA_TOKEN", "external-token")
    m = mod.PrReviewModule()  # does not raise
    assert m.repos == [_REPO]


def test_malformed_repo_entry_raises(mod, monkeypatch):
    monkeypatch.setenv("PRREVIEW_REPOS", "not-a-repo")
    with pytest.raises(ValueError, match="owner"):
        mod.PrReviewModule()


# --- dedup decision (in code, not in the LLM) -------------------------------

def test_unreviewed_pr_needs_review(mod, module):
    module._client.pulls = [_pull(1, "aaa1111")]
    result = asyncio.run(module.list_prs_needing_review())
    assert result["success"] is True
    assert [p["number"] for p in result["prs"]] == [1]
    assert result["prs"][0]["previously_reviewed_sha"] is None


def test_unchanged_pr_is_skipped(mod, module):
    module._client.pulls = [_pull(1, "aaa1111")]
    module._client.comments = {1: [_sticky(mod, "aaa1111")]}
    result = asyncio.run(module.list_prs_needing_review())
    assert result["prs"] == []
    assert result["skipped_unchanged"] == 1


def test_changed_pr_needs_review_again_with_previous_sha(mod, module):
    module._client.pulls = [_pull(1, "bbb2222")]
    module._client.comments = {1: [_sticky(mod, "aaa1111")]}
    result = asyncio.run(module.list_prs_needing_review())
    assert [p["number"] for p in result["prs"]] == [1]
    assert result["prs"][0]["previously_reviewed_sha"] == "aaa1111"


def test_draft_prs_are_skipped(mod, module):
    module._client.pulls = [_pull(1, "aaa1111", draft=True)]
    result = asyncio.run(module.list_prs_needing_review())
    assert result["prs"] == []
    assert result["skipped_drafts"] == 1


def test_pr_without_head_sha_is_skipped(mod, module):
    pull = _pull(1, "aaa1111")
    pull["head"]["sha"] = None
    module._client.pulls = [pull]
    result = asyncio.run(module.list_prs_needing_review())
    assert result["prs"] == []


def test_per_run_cap_is_enforced(mod, module):
    module._client.pulls = [_pull(i, f"aaa000{i}") for i in range(1, 5)]
    result = asyncio.run(module.list_prs_needing_review())
    assert len(result["prs"]) == 2  # PRREVIEW_MAX_PRS_PER_RUN=2
    assert result["total_needing_review"] == 4
    assert result["skipped_over_cap"] == 2


# --- diff size guard ---------------------------------------------------------

def test_small_diff_is_returned(mod, module):
    module._client.diff = "line\n" * 5
    result = asyncio.run(module.get_pr_diff(_REPO, 1))
    assert result["success"] is True
    assert result["too_large"] is False
    assert result["diff_lines"] == 5


def test_oversized_diff_is_guarded(mod, module):
    module._client.diff = "line\n" * 11  # PRREVIEW_MAX_DIFF_LINES=10
    result = asyncio.run(module.get_pr_diff(_REPO, 1))
    assert result["too_large"] is True
    assert result["diff"] is None
    assert "SKIPPED_TOO_LARGE" in result["message"]


# --- repo allowlist ----------------------------------------------------------

def test_get_pr_diff_rejects_non_allowlisted_repo(mod, module):
    result = asyncio.run(module.get_pr_diff("evil/repo", 1))
    assert result["success"] is False
    assert "allowlist" in result["error"]


def test_post_pr_review_rejects_non_allowlisted_repo(mod, module):
    result = asyncio.run(module.post_pr_review("evil/repo", 1, "aaa1111", "APPROVE", "x"))
    assert result["success"] is False
    assert "allowlist" in result["error"]


# --- sticky comment: reviews never stack -------------------------------------

def test_first_review_creates_the_sticky_comment(mod, module):
    result = asyncio.run(
        module.post_pr_review(_REPO, 1, "aaa1111", "APPROVE", "LGTM — no findings.")
    )
    assert result["success"] is True
    assert result["action"] == "created"
    assert len(module._client.created) == 1
    _, body = module._client.created[0]
    assert mod.parse_marker(body) == ("aaa1111", "APPROVE")


def test_second_review_edits_the_same_comment(mod, module):
    module._client.comments = {1: [_sticky(mod, "aaa1111", comment_id=77)]}
    result = asyncio.run(
        module.post_pr_review(_REPO, 1, "bbb2222", "REQUEST_CHANGES", "findings...")
    )
    assert result["action"] == "updated"
    assert module._client.created == []
    comment_id, body = module._client.edited[0]
    assert comment_id == 77
    assert mod.parse_marker(body) == ("bbb2222", "REQUEST_CHANGES")


def test_dedup_ignores_marker_quoted_by_a_human(mod, module):
    module._client.pulls = [_pull(1, "aaa1111")]
    module._client.comments = {1: [_human_quote(mod, "aaa1111")]}
    result = asyncio.run(module.list_prs_needing_review())
    assert [p["number"] for p in result["prs"]] == [1]
    assert result["prs"][0]["previously_reviewed_sha"] is None


def test_post_review_edits_bot_comment_not_a_newer_human_quote(mod, module):
    module._client.comments = {
        1: [
            _sticky(mod, "aaa1111", comment_id=77),
            _human_quote(mod, "aaa1111", comment_id=88),
        ]
    }
    result = asyncio.run(module.post_pr_review(_REPO, 1, "bbb2222", "APPROVE", "ok"))
    assert result["action"] == "updated"
    assert module._client.edited[0][0] == 77
    assert module._client.created == []


def test_post_pr_review_validates_verdict_and_sha_and_body(mod, module):
    bad_verdict = asyncio.run(module.post_pr_review(_REPO, 1, "aaa1111", "SHIP_IT", "x"))
    assert bad_verdict["success"] is False and "verdict" in bad_verdict["error"].lower()

    bad_sha = asyncio.run(module.post_pr_review(_REPO, 1, "not a sha", "APPROVE", "x"))
    assert bad_sha["success"] is False and "head_sha" in bad_sha["error"]

    empty_body = asyncio.run(module.post_pr_review(_REPO, 1, "aaa1111", "APPROVE", "  "))
    assert empty_body["success"] is False and "body" in empty_body["error"]

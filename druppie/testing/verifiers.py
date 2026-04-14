"""Layer 2: Side-effect verifiers for post-execution state checks.

Verifiers check the real world state after tool calls execute:
files in Gitea repos, git branches, mermaid syntax validity, etc.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from uuid import UUID

import httpx
from sqlalchemy.orm import Session as DbSession

from druppie.db.models import Project, Session as SessionModel

logger = logging.getLogger(__name__)


def _gitea_auth() -> tuple[str, str]:
    """Get Gitea admin credentials from environment.

    Raises ValueError if credentials are not configured.
    """
    user = os.getenv("GITEA_ADMIN_USER")
    password = os.getenv("GITEA_ADMIN_PASSWORD")
    if not user or not password:
        raise ValueError(
            "GITEA_ADMIN_USER and GITEA_ADMIN_PASSWORD environment variables must be set"
        )
    return (user, password)


@dataclass
class VerifyResult:
    verifier: str
    passed: bool
    message: str


def run_verifiers(
    verify_checks: list,
    session_id: UUID,
    db: DbSession,
    gitea_url: str | None = None,
) -> list[VerifyResult]:
    """Run all verify checks against real state."""
    results = []
    for check in verify_checks:
        vr = _run_single_verify(check, session_id, db, gitea_url)
        results.append(vr)
    return results


def _get_project_repo_info(session_id: UUID, db: DbSession) -> tuple[str | None, str | None]:
    """Get repo owner and name for the session's project."""
    session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not session or not session.project_id:
        return None, None
    project = db.query(Project).filter(Project.id == session.project_id).first()
    if not project:
        return None, None
    return project.repo_owner or "druppie_admin", project.repo_name or project.name


def _run_single_verify(check, session_id: UUID, db: DbSession, gitea_url: str | None) -> VerifyResult:
    """Run a single verify check."""
    # Each check object has one non-None field that determines the verifier type

    if check.file_exists is not None:
        return _verify_file_exists(check.file_exists, session_id, db, gitea_url)

    if check.file_not_empty is not None:
        return _verify_file_not_empty(check.file_not_empty, session_id, db, gitea_url)

    if check.file_contains is not None:
        path = check.file_contains.get("path", "")
        content = check.file_contains.get("content", "")
        return _verify_file_contains(path, content, session_id, db, gitea_url)

    if check.file_matches is not None:
        path = check.file_matches.get("path", "")
        pattern = check.file_matches.get("pattern", "")
        return _verify_file_matches(path, pattern, session_id, db, gitea_url)

    if check.mermaid_valid is not None:
        return _verify_mermaid_valid(check.mermaid_valid, session_id, db, gitea_url)

    if check.git_branch_exists is not None:
        return _verify_git_branch_exists(check.git_branch_exists, session_id, db, gitea_url)

    if check.gitea_repo_exists is not None:
        return _verify_gitea_repo_exists(session_id, db, gitea_url)

    return VerifyResult("unknown", False, "No recognized verify check found")


def _gitea_get_file(path: str, owner: str, repo: str, gitea_url: str) -> tuple[bool, str]:
    """Fetch file content from Gitea. Returns (exists, content)."""
    try:
        r = httpx.get(
            f"{gitea_url}/api/v1/repos/{owner}/{repo}/contents/{path}",
            auth=_gitea_auth(),
            timeout=10,
        )
        if r.status_code == 404:
            return False, ""
        r.raise_for_status()
        data = r.json()
        import base64
        content = base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace")
        return True, content
    except Exception as e:
        return False, str(e)


def _verify_file_exists(path: str, session_id: UUID, db: DbSession, gitea_url: str | None) -> VerifyResult:
    if not gitea_url:
        return VerifyResult(f"file_exists:{path}", False, "No gitea_url configured")
    owner, repo = _get_project_repo_info(session_id, db)
    if not repo:
        return VerifyResult(f"file_exists:{path}", False, "No project repo found for session")
    exists, _ = _gitea_get_file(path, owner, repo, gitea_url)
    if exists:
        return VerifyResult(f"file_exists:{path}", True, f"File {path} exists")
    return VerifyResult(f"file_exists:{path}", False, f"File {path} not found in {owner}/{repo}")


def _verify_file_not_empty(path: str, session_id: UUID, db: DbSession, gitea_url: str | None) -> VerifyResult:
    if not gitea_url:
        return VerifyResult(f"file_not_empty:{path}", False, "No gitea_url configured")
    owner, repo = _get_project_repo_info(session_id, db)
    if not repo:
        return VerifyResult(f"file_not_empty:{path}", False, "No project repo found")
    exists, content = _gitea_get_file(path, owner, repo, gitea_url)
    if not exists:
        return VerifyResult(f"file_not_empty:{path}", False, f"File {path} not found")
    if not content.strip():
        return VerifyResult(f"file_not_empty:{path}", False, f"File {path} is empty")
    return VerifyResult(f"file_not_empty:{path}", True, f"File {path} has {len(content)} chars")


def _verify_file_contains(path: str, expected: str, session_id: UUID, db: DbSession, gitea_url: str | None) -> VerifyResult:
    if not gitea_url:
        return VerifyResult(f"file_contains:{path}", False, "No gitea_url configured")
    owner, repo = _get_project_repo_info(session_id, db)
    if not repo:
        return VerifyResult(f"file_contains:{path}", False, "No project repo found")
    exists, content = _gitea_get_file(path, owner, repo, gitea_url)
    if not exists:
        return VerifyResult(f"file_contains:{path}", False, f"File {path} not found")
    if expected in content:
        return VerifyResult(f"file_contains:{path}", True, f"File contains '{expected}'")
    return VerifyResult(f"file_contains:{path}", False, f"File does not contain '{expected}'")


def _verify_file_matches(path: str, pattern: str, session_id: UUID, db: DbSession, gitea_url: str | None) -> VerifyResult:
    if not gitea_url:
        return VerifyResult(f"file_matches:{path}", False, "No gitea_url configured")
    owner, repo = _get_project_repo_info(session_id, db)
    if not repo:
        return VerifyResult(f"file_matches:{path}", False, "No project repo found")
    exists, content = _gitea_get_file(path, owner, repo, gitea_url)
    if not exists:
        return VerifyResult(f"file_matches:{path}", False, f"File {path} not found")
    try:
        if re.search(pattern, content):
            return VerifyResult(f"file_matches:{path}", True, f"File matches pattern '{pattern}'")
        return VerifyResult(f"file_matches:{path}", False, f"File does not match pattern '{pattern}'")
    except re.error as exc:
        return VerifyResult(f"file_matches:{path}", False, f"Invalid regex pattern '{pattern}': {exc}")


def _verify_mermaid_valid(path: str, session_id: UUID, db: DbSession, gitea_url: str | None) -> VerifyResult:
    """Verify all mermaid blocks in a file are syntactically valid."""
    if not gitea_url:
        return VerifyResult(f"mermaid_valid:{path}", False, "No gitea_url configured")
    owner, repo = _get_project_repo_info(session_id, db)
    if not repo:
        return VerifyResult(f"mermaid_valid:{path}", False, "No project repo found")
    exists, content = _gitea_get_file(path, owner, repo, gitea_url)
    if not exists:
        return VerifyResult(f"mermaid_valid:{path}", False, f"File {path} not found")

    # Extract mermaid blocks
    blocks = re.findall(r"```mermaid\s*\n(.*?)```", content, re.DOTALL)
    if not blocks:
        return VerifyResult(f"mermaid_valid:{path}", True, "No mermaid blocks found")

    # Basic syntax validation — check for common mermaid diagram types
    valid_starts = ["flowchart", "graph", "sequenceDiagram", "classDiagram",
                    "stateDiagram", "erDiagram", "gantt", "pie", "gitgraph",
                    "mindmap", "timeline", "journey", "C4Context"]
    for i, block in enumerate(blocks):
        stripped = block.strip()
        if not stripped:
            return VerifyResult(f"mermaid_valid:{path}", False, f"Mermaid block {i+1} is empty")
        first_line = stripped.split("\n")[0].strip()
        first_word = first_line.split()[0] if first_line.split() else ""
        if not any(first_word.startswith(s) for s in valid_starts):
            return VerifyResult(f"mermaid_valid:{path}", False,
                              f"Mermaid block {i+1} has unrecognized type: '{first_word}'")

    return VerifyResult(f"mermaid_valid:{path}", True, f"All {len(blocks)} mermaid blocks valid")


def _verify_git_branch_exists(branch: str, session_id: UUID, db: DbSession, gitea_url: str | None) -> VerifyResult:
    if not gitea_url:
        return VerifyResult(f"git_branch_exists:{branch}", False, "No gitea_url configured")
    owner, repo = _get_project_repo_info(session_id, db)
    if not repo:
        return VerifyResult(f"git_branch_exists:{branch}", False, "No project repo found")
    try:
        r = httpx.get(
            f"{gitea_url}/api/v1/repos/{owner}/{repo}/branches/{branch}",
            auth=_gitea_auth(),
            timeout=10,
        )
        if r.status_code == 200:
            return VerifyResult(f"git_branch_exists:{branch}", True, f"Branch {branch} exists")
        return VerifyResult(f"git_branch_exists:{branch}", False, f"Branch {branch} not found (HTTP {r.status_code})")
    except Exception as e:
        return VerifyResult(f"git_branch_exists:{branch}", False, f"Error checking branch: {e}")


def _verify_gitea_repo_exists(session_id: UUID, db: DbSession, gitea_url: str | None) -> VerifyResult:
    if not gitea_url:
        return VerifyResult("gitea_repo_exists", False, "No gitea_url configured")
    owner, repo = _get_project_repo_info(session_id, db)
    if not repo:
        return VerifyResult("gitea_repo_exists", False, "No project repo found for session")
    try:
        r = httpx.get(
            f"{gitea_url}/api/v1/repos/{owner}/{repo}",
            auth=_gitea_auth(),
            timeout=10,
        )
        if r.status_code == 200:
            return VerifyResult("gitea_repo_exists", True, f"Repo {owner}/{repo} exists")
        return VerifyResult("gitea_repo_exists", False, f"Repo {owner}/{repo} not found (HTTP {r.status_code})")
    except Exception as e:
        return VerifyResult("gitea_repo_exists", False, f"Error checking repo: {e}")

"""Tests for sandbox container management in module-coding v1 tools.

Covers: docker run command construction, security flags, runtime/user flags,
cache volume, container lifecycle, and command blocklist.
"""

import importlib.util
import re
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Module loading
#
# druppie/mcp-servers/module-coding/v1/tools.py uses hyphens in directory names
# and has no __init__.py at the mcp-servers/ or module-coding/ levels, so we
# load it via importlib with synthetic parent packages to satisfy the relative
# import (from .mermaid_validator import ...).
# ---------------------------------------------------------------------------

_V1_DIR = (
    Path(__file__).resolve().parents[2] / "mcp-servers" / "module-coding" / "v1"
)
_TOOLS_FILE = _V1_DIR / "tools.py"

pkg_mc = types.ModuleType("module_coding")
pkg_mc.__path__ = []
pkg_mc.__package__ = "module_coding"
sys.modules.setdefault("module_coding", pkg_mc)

pkg_v1 = types.ModuleType("module_coding.v1")
pkg_v1.__path__ = [str(_V1_DIR)]
pkg_v1.__package__ = "module_coding.v1"
sys.modules.setdefault("module_coding.v1", pkg_v1)

sys.modules.setdefault("module_coding.v1.mermaid_validator", MagicMock())

_spec = importlib.util.spec_from_file_location(
    "module_coding.v1.tools", str(_TOOLS_FILE)
)
tools = importlib.util.module_from_spec(_spec)
tools.__package__ = "module_coding.v1"
sys.modules["module_coding.v1.tools"] = tools
_spec.loader.exec_module(tools)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _capture_docker_run_cmd(**kwargs):
    """Call _create_sandbox_container with mocked internals and return the
    ``docker run`` command list that was constructed."""
    mock_dr = AsyncMock(return_value=(0, "abc123container\n", ""))
    mock_exec = AsyncMock(return_value=(0, "", ""))
    with patch.object(tools, "_docker_run", mock_dr), patch.object(
        tools, "_exec_in_container", mock_exec
    ):
        await tools._create_sandbox_container(
            session_id="test-session-12345678",
            git_scope="current_project",
            **kwargs,
        )
    for call_obj in mock_dr.call_args_list:
        cmd = call_obj[0][0]
        if len(cmd) >= 2 and cmd[:2] == ["docker", "run"]:
            return cmd
    raise AssertionError("No docker run call found in _docker_run mocks")


# ---------------------------------------------------------------------------
# Test: Command Construction
# ---------------------------------------------------------------------------


class TestCommandConstruction:
    @pytest.fixture(autouse=True)
    def clean_state(self):
        tools.sandbox_containers.clear()
        tools._container_locks.clear()
        yield
        tools.sandbox_containers.clear()
        tools._container_locks.clear()

    @pytest.mark.asyncio
    async def test_security_flags_always_present(self):
        cmd = await _capture_docker_run_cmd()
        idx = cmd.index("--security-opt")
        assert cmd[idx + 1] == "no-new-privileges"
        idx = cmd.index("--cap-drop")
        assert cmd[idx + 1] == "ALL"
        idx = cmd.index("--cap-add")
        assert cmd[idx + 1] == "NET_RAW"
        assert "--memory" in cmd
        assert "--pids-limit" in cmd
        assert "--cpus" in cmd
        idx = cmd.index("--tmpfs")
        assert cmd[idx + 1] == "/tmp:size=512m"

    @pytest.mark.asyncio
    async def test_runtime_flag_default(self):
        """Default SANDBOX_RUNTIME is sysbox-runc — --runtime is always present."""
        cmd = await _capture_docker_run_cmd()
        assert "--runtime" in cmd
        idx = cmd.index("--runtime")
        assert cmd[idx + 1] == tools.SANDBOX_RUNTIME

    @pytest.mark.asyncio
    async def test_runtime_flag_sysbox(self):
        with patch.object(tools, "SANDBOX_RUNTIME", "sysbox-runc"):
            cmd = await _capture_docker_run_cmd()
        idx = cmd.index("--runtime")
        assert cmd[idx + 1] == "sysbox-runc"

    @pytest.mark.asyncio
    async def test_runtime_flag_kata(self):
        with patch.object(tools, "SANDBOX_RUNTIME", "kata-runtime"):
            cmd = await _capture_docker_run_cmd()
        idx = cmd.index("--runtime")
        assert cmd[idx + 1] == "kata-runtime"

    @pytest.mark.asyncio
    async def test_no_user_flag(self):
        cmd = await _capture_docker_run_cmd()
        assert "--user" not in cmd

    @pytest.mark.asyncio
    async def test_cache_volume_mounted(self):
        with patch.object(tools, "SANDBOX_CACHE_VOLUME", "my_cache_vol"):
            cmd = await _capture_docker_run_cmd()
        idx = cmd.index("-v")
        assert cmd[idx + 1] == "my_cache_vol:/cache"

    @pytest.mark.asyncio
    async def test_cache_env_vars_set(self):
        cmd = await _capture_docker_run_cmd()
        assert "-e" in cmd
        assert "UV_CACHE_DIR=/cache/uv" in cmd
        assert "PIP_CACHE_DIR=/cache/pip" in cmd

    @pytest.mark.asyncio
    async def test_image_and_sleep(self):
        with patch.object(tools, "SANDBOX_IMAGE", "myimage:tag"):
            cmd = await _capture_docker_run_cmd()
        idx = cmd.index("myimage:tag")
        assert cmd[idx + 1] == "bash"
        assert cmd[idx + 2] == "-c"
        assert "dockerd" in cmd[idx + 3]
        assert "sleep infinity" in cmd[idx + 3]


# ---------------------------------------------------------------------------
# Test: Container Lifecycle
# ---------------------------------------------------------------------------


class TestContainerLifecycle:
    @pytest.fixture(autouse=True)
    def clean_state(self):
        tools.sandbox_containers.clear()
        tools._container_locks.clear()
        yield
        tools.sandbox_containers.clear()
        tools._container_locks.clear()

    @pytest.mark.asyncio
    async def test_resolve_returns_existing_container(self):
        tools.sandbox_containers["sess123::current_project"] = {
            "container_name": "druppie-sess123-current_project",
            "container_id": "abc123def456",
            "git_scope": "current_project",
            "session_id": "sess123",
            "branch": "main",
            "created_at": 0.0,
            "repo_name": "repo",
            "repo_owner": "org",
        }
        # Container is running AND the liveness probe (echo ok) succeeds first
        # try, so the existing container is reused (no recreate).
        with patch.object(
            tools, "_is_container_running", AsyncMock(return_value=True)
        ), patch.object(
            tools, "_exec_in_container", AsyncMock(return_value=(0, "ok", ""))
        ):
            result = await tools._resolve_container(
                session_id="sess123",
                git_scope="current_project",
            )
        assert result == "druppie-sess123-current_project"

    @pytest.mark.asyncio
    async def test_resolve_reuses_after_transient_probe_blip(self):
        # Fix #4: a single failed liveness probe is often a transient setns /
        # port-forward blip. Recreating on it triggers a fresh clone and throws
        # away the agent's uncommitted work, so we re-probe up to 3x. A probe
        # that fails once then succeeds must REUSE the container, not recreate.
        tools.sandbox_containers["sess123::current_project"] = {
            "container_name": "druppie-sess123-current_project",
            "container_id": "abc123def456",
            "git_scope": "current_project",
            "session_id": "sess123",
            "branch": "main",
            "created_at": 0.0,
            "repo_name": "repo",
            "repo_owner": "org",
        }
        # First probe fails (rc=1), second succeeds (rc=0).
        probe = AsyncMock(side_effect=[(1, "", "setns blip"), (0, "ok", "")])
        mock_create = AsyncMock(return_value="druppie-should-not-be-called")
        with patch.object(
            tools, "_is_container_running", AsyncMock(return_value=True)
        ), patch.object(tools, "_exec_in_container", probe), patch.object(
            tools, "_create_sandbox_container", mock_create
        ), patch.object(tools.asyncio, "sleep", AsyncMock()):
            result = await tools._resolve_container(
                session_id="sess123",
                git_scope="current_project",
            )
        assert result == "druppie-sess123-current_project"
        assert probe.call_count == 2  # re-probed after the blip
        mock_create.assert_not_called()  # container was NOT recreated

    @pytest.mark.asyncio
    async def test_resolve_recreates_after_persistent_probe_failure(self):
        # Fix #4: only after the probe fails all 3 times do we conclude the
        # sandbox is wedged and recreate it (destroying the old claim first).
        tools.sandbox_containers["sess123::current_project"] = {
            "container_name": "druppie-sess123-current_project",
            "container_id": "abc123def456",
            "git_scope": "current_project",
            "session_id": "sess123",
            "branch": "main",
            "created_at": 0.0,
            "repo_name": "repo",
            "repo_owner": "org",
        }
        probe = AsyncMock(return_value=(1, "", "setns: no such process"))
        mock_create = AsyncMock(return_value="druppie-sess123-new")

        async def _fake_destroy(sid, scope):
            tools.sandbox_containers.pop(f"{sid}::{scope}", None)

        with patch.object(
            tools, "_is_container_running", AsyncMock(return_value=True)
        ), patch.object(tools, "_exec_in_container", probe), patch.object(
            tools, "_destroy_container", AsyncMock(side_effect=_fake_destroy)
        ), patch.object(
            tools, "_create_sandbox_container", mock_create
        ), patch.object(tools.asyncio, "sleep", AsyncMock()):
            result = await tools._resolve_container(
                session_id="sess123",
                git_scope="current_project",
            )
        assert result == "druppie-sess123-new"
        assert probe.call_count == 3  # exhausted all retries before recreating
        assert "sess123::current_project" not in tools.sandbox_containers
        mock_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_resolve_recreates_dead_container(self):
        tools.sandbox_containers["sess123::current_project"] = {
            "container_name": "druppie-sess123-current_project",
            "container_id": "abc123def456",
            "git_scope": "current_project",
            "session_id": "sess123",
            "branch": "main",
            "created_at": 0.0,
            "repo_name": "repo",
            "repo_owner": "org",
        }
        mock_create = AsyncMock(return_value="druppie-sess123-new")

        async def _fake_destroy(sid, scope):
            tools.sandbox_containers.pop(f"{sid}::{scope}", None)

        with patch.object(
            tools, "_is_container_running", AsyncMock(return_value=False)
        ), patch.object(
            tools, "_get_container_death_reason", AsyncMock(return_value="exited")
        ), patch.object(
            tools, "_destroy_container", AsyncMock(side_effect=_fake_destroy)
        ), patch.object(tools, "_create_sandbox_container", mock_create):
            result = await tools._resolve_container(
                session_id="sess123",
                git_scope="current_project",
            )
        assert result == "druppie-sess123-new"
        assert "sess123::current_project" not in tools.sandbox_containers
        mock_create.assert_called_once_with(
            "sess123", "current_project", None, None, agent_networks=None
        )

    @pytest.mark.asyncio
    async def test_resolve_creates_new_container(self):
        mock_create = AsyncMock(return_value="druppie-new-container")
        with patch.object(tools, "_create_sandbox_container", mock_create):
            result = await tools._resolve_container(
                session_id="sess456",
                git_scope="current_project",
            )
        assert result == "druppie-new-container"
        mock_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_destroy_removes_container(self):
        tools.sandbox_containers["sess123::current_project"] = {
            "container_name": "druppie-sess123-current_project",
            "container_id": "abc123def456",
            "git_scope": "current_project",
            "session_id": "sess123",
            "branch": "main",
            "created_at": 0.0,
            "repo_name": "repo",
            "repo_owner": "org",
        }
        mock_dr = AsyncMock(return_value=(0, "", ""))
        with patch.object(tools, "_docker_run", mock_dr):
            await tools._destroy_container("sess123", "current_project")
        assert "sess123::current_project" not in tools.sandbox_containers
        cmds = [c[0][0] for c in mock_dr.call_args_list]
        assert any("stop" in c for c in cmds)
        assert any("rm" in c for c in cmds)


# ---------------------------------------------------------------------------
# Test: Command Blocklist
# ---------------------------------------------------------------------------


class TestCommandBlocklist:
    @staticmethod
    def _is_blocked(cmd: str) -> bool:
        return any(
            re.search(p, cmd, re.IGNORECASE) for p in tools.BLOCKED_COMMAND_PATTERNS
        )

    def test_blocklist_catches_rm_rf_root(self):
        assert self._is_blocked("rm -rf /")
        assert self._is_blocked("rm -rf /home")

    def test_blocklist_catches_mkfs(self):
        assert self._is_blocked("mkfs /dev/sda1")

    def test_blocklist_catches_dd(self):
        assert self._is_blocked("dd if=/dev/zero of=/dev/sda")

    def test_blocklist_catches_sudo(self):
        assert self._is_blocked("sudo apt install")

    def test_blocklist_allows_safe_commands(self):
        assert not self._is_blocked("ls -la")
        assert not self._is_blocked("git status")
        assert not self._is_blocked("pip install pytest")

    def test_blocklist_allows_docker_commands(self):
        assert not self._is_blocked("docker ps")


# ---------------------------------------------------------------------------
# Test: push base-branch handling (fix #5)
#
# The git bundle must be thinned against the branch the repo was cloned from
# (recorded as ``base_branch``), NOT a hardcoded "main": update_core clones
# colab-dev, so ``^origin/main`` would bundle the wrong commit range (and the
# host-side prerequisite fetch would pull the wrong branch). push_changes is a
# FastMCP @mcp.tool wrapper (awkward to invoke directly), so we pin the fix at
# the source level — the same approach used for the cluster-only wipe command.
# ---------------------------------------------------------------------------


class TestPushBaseBranch:
    def _source(self):
        return _TOOLS_FILE.read_text(encoding="utf-8")

    def test_entry_records_base_branch(self):
        # Both the docker and k8s creation paths must persist base_branch so
        # push_changes can recover it. Two entry dicts -> two occurrences.
        assert self._source().count('"base_branch": branch') >= 2

    def test_push_reads_recorded_base_branch(self):
        assert 'base_branch = entry.get("base_branch") or "main"' in self._source()

    def test_bundle_thinned_against_base_branch(self):
        src = self._source()
        assert 'f"^origin/{base_branch}"' in src
        # The old hardcoded form must not linger in the bundle construction.
        assert '"^origin/main"' not in src

"""Unit tests for k8s_sandbox.py pure logic (no cluster / SDK required).

The agent-sandbox SDK and the kubernetes client are imported *lazily* — only
inside ``K8sSandboxManager.__init__`` and ``cleanup_orphan_claims`` — so the
module top level loads with the standard library alone. That lets us unit-test
the credential-isolation guarantee and the mode dispatch in plain CI, without a
running cluster (which is exactly the gVisor path's test gap: the end-to-end
proof lives in ``testing/tools/sandbox-gvisor-push-e2e.yaml`` and needs a live
stack).

Loaded via importlib because ``druppie/mcp-servers/module-coding`` uses hyphens
and has no package ``__init__.py`` (same approach as ``test_sandbox.py``).
"""

import asyncio
import base64 as _b64
import importlib.util
import posixpath
import shlex
import sys
from pathlib import Path

import pytest

_K8S_SANDBOX_FILE = (
    Path(__file__).resolve().parents[2]
    / "mcp-servers"
    / "module-coding"
    / "k8s_sandbox.py"
)

_spec = importlib.util.spec_from_file_location(
    "k8s_sandbox_under_test", str(_K8S_SANDBOX_FILE)
)
k8s_sandbox = importlib.util.module_from_spec(_spec)
# Register before exec: the module defines an @dataclass, whose processing looks
# the module up in sys.modules by __module__ (fails with NoneType otherwise).
sys.modules["k8s_sandbox_under_test"] = k8s_sandbox
_spec.loader.exec_module(k8s_sandbox)


# ---------------------------------------------------------------------------
# _strip_credentials — the "sandbox holds no git credentials" guarantee.
# After an authenticated host-side clone the origin URL is rewritten to this
# stripped form so no token persists in the sandbox's .git/config.
# ---------------------------------------------------------------------------


class TestStripCredentials:
    def test_strips_user_and_password(self):
        assert (
            k8s_sandbox._strip_credentials(
                "https://user:token@gitea.example.org/org/repo.git"
            )
            == "https://gitea.example.org/org/repo.git"
        )

    def test_strips_token_only_userinfo(self):
        assert (
            k8s_sandbox._strip_credentials(
                "https://ghp_abc123@gitea.example.org/org/repo.git"
            )
            == "https://gitea.example.org/org/repo.git"
        )

    def test_preserves_port(self):
        assert (
            k8s_sandbox._strip_credentials(
                "https://user:pw@gitea.example.org:3000/org/repo.git"
            )
            == "https://gitea.example.org:3000/org/repo.git"
        )

    def test_noop_when_no_credentials(self):
        url = "https://gitea.example.org/org/repo.git"
        assert k8s_sandbox._strip_credentials(url) == url

    def test_no_secret_substring_survives(self):
        # The core security property: nothing of the userinfo leaks through.
        secret = "s3cr3t-token-value"
        out = k8s_sandbox._strip_credentials(
            "https://bot-user:%s@gitea.example.org/org/repo.git" % secret
        )
        assert secret not in out
        assert "bot-user" not in out
        assert "@" not in out


# ---------------------------------------------------------------------------
# get_sandbox_manager — mode dispatch. Docker mode must not touch the SDK.
# ---------------------------------------------------------------------------


class TestManagerDispatch:
    def test_docker_mode_returns_none(self, monkeypatch):
        monkeypatch.setattr(k8s_sandbox, "SANDBOX_MODE", "docker")
        assert k8s_sandbox.get_sandbox_manager() is None


# ---------------------------------------------------------------------------
# SandboxHandle — dataclass defaults used throughout tools.py.
# ---------------------------------------------------------------------------


class TestSandboxHandle:
    def test_defaults(self):
        handle = k8s_sandbox.SandboxHandle(
            sandbox_id="sb-1", session_id="sess-1", git_scope="current_project"
        )
        assert handle.branch == "main"
        assert handle.created_at > 0
        assert handle._backend is None


# ---------------------------------------------------------------------------
# Fake agent-sandbox SDK sandbox: an in-memory file store fronted by a tiny
# POSIX-ish shell interpreter. Enough to exercise write_file / read_file /
# create() round-trips WITHOUT a live gVisor cluster or the real SDK (which is
# imported lazily, only inside K8sSandboxManager.__init__). This is the CI-side
# proxy for the cluster-only paths; the true end-to-end proof lives in
# testing/tools/sandbox-gvisor-push-e2e.yaml.
# ---------------------------------------------------------------------------


class _CmdResult:
    def __init__(self, exit_code=0, stdout="", stderr=""):
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr


class _FakeFiles:
    """Stand-in for sandbox.files — the SDK upload/download endpoints.

    ``write`` mirrors the upload endpoint used by write_file: a RELATIVE name
    lands at /app/<name> (matching the real endpoint, which 500s on absolute
    paths); an absolute name is stored verbatim. ``read`` mirrors the native
    download endpoint now used by read_file_bytes: with ``allow_unsafe_paths``
    the caller's path is honoured verbatim (so absolute bundle paths like
    ``/tmp/x.bundle`` resolve correctly); without it the SDK's sanitiser strips
    the leading ``/`` and resolves relative names under /app.
    """

    def __init__(self, fs):
        self._fs = fs

    async def write(self, name, content):
        if isinstance(content, str):
            content = content.encode("utf-8")
        abspath = name if name.startswith("/") else "/app/" + name
        self._fs[abspath] = bytes(content)

    async def read(self, name, timeout=60, allow_unsafe_paths=False):
        if allow_unsafe_paths:
            abspath = name  # verbatim — absolute paths preserved
        else:
            abspath = "/app/" + name.lstrip("/")
        if abspath not in self._fs:
            # The real connector raises on the download endpoint's 404.
            raise RuntimeError("download %s: not found" % abspath)
        return self._fs[abspath]


class FakeSandbox:
    """Minimal stand-in for an agent-sandbox SDK sandbox object.

    Implements just enough of a shell (over an in-memory file store) that the
    manager's write_file/read_file/file_exists command strings actually move
    bytes around. commands.run always receives ``bash -c '<inner>'`` from the
    manager; we split on &&/||/; honouring exit codes so patterns like
    ``test -f X && echo yes || echo no`` behave correctly.
    """

    def __init__(self, sandbox_id="sb-test"):
        self.sandbox_id = sandbox_id
        self._fs = {}
        self.files = _FakeFiles(self._fs)
        self.commands = self  # manager calls sandbox.commands.run(...)
        self.terminated = False
        self.run_log = []

    async def terminate(self):
        self.terminated = True

    async def run(self, cmd, timeout=None):
        self.run_log.append(cmd)
        toks = shlex.split(cmd)
        if len(toks) >= 3 and toks[0] == "bash" and toks[1] == "-c":
            inner = toks[2]
        else:
            inner = cmd
        return self._run_shell(inner)

    def _resolve(self, path, cwd):
        if path.startswith("/"):
            return posixpath.normpath(path)
        return posixpath.normpath(posixpath.join(cwd, path))

    def _run_shell(self, inner):
        tokens = shlex.split(inner)
        groups, ops, cur = [], [], []
        for t in tokens:
            if t in ("&&", "||", ";"):
                groups.append(cur)
                ops.append(t)
                cur = []
            else:
                cur.append(t)
        groups.append(cur)

        rc, out, err, cwd = 0, "", "", "/workspace"
        for i, g in enumerate(groups):
            if i > 0:
                op = ops[i - 1]
                if op == "&&" and rc != 0:
                    continue
                if op == "||" and rc == 0:
                    continue
            rc, o, e, cwd = self._run_simple(g, cwd)
            out += o
            err += e
        return _CmdResult(rc, out, err)

    def _run_simple(self, argv, cwd):
        if not argv:
            return 0, "", "", cwd
        cmd = argv[0]
        if cmd == "cd":
            return 0, "", "", (self._resolve(argv[1], cwd) if len(argv) > 1 else cwd)
        if cmd == "mkdir":
            return 0, "", "", cwd
        if cmd == "mv":
            args = [a for a in argv[1:] if not a.startswith("-")]
            src, dst = self._resolve(args[0], cwd), self._resolve(args[1], cwd)
            if src in self._fs:
                self._fs[dst] = self._fs.pop(src)
                return 0, "", "", cwd
            return 1, "", "mv: %s: No such file or directory" % src, cwd
        if cmd == "rm":
            for a in (a for a in argv[1:] if not a.startswith("-")):
                self._fs.pop(self._resolve(a, cwd), None)
            return 0, "", "", cwd
        if cmd == "cat":
            p = self._resolve(argv[1], cwd)
            if p in self._fs:
                return 0, self._fs[p].decode("utf-8", "replace"), "", cwd
            return 1, "", "cat: %s: No such file or directory" % p, cwd
        if cmd == "base64":
            p = self._resolve(argv[1], cwd)
            if p in self._fs:
                return 0, _b64.b64encode(self._fs[p]).decode("ascii"), "", cwd
            return 1, "", "base64: %s: No such file or directory" % p, cwd
        if cmd == "test":
            p = self._resolve(argv[2], cwd)  # test -f <path>
            return (0 if p in self._fs else 1), "", "", cwd
        if cmd == "echo":
            return 0, " ".join(argv[1:]) + "\n", "", cwd
        if cmd == "find":
            for k in [k for k in self._fs if k.startswith("/workspace/")]:
                del self._fs[k]
            return 0, "", "", cwd
        # git / anything else: succeed silently (git config, etc.)
        return 0, "", "", cwd


def _bare_manager():
    """A K8sSandboxManager without __init__ (which would import the real SDK)."""
    mgr = k8s_sandbox.K8sSandboxManager.__new__(k8s_sandbox.K8sSandboxManager)
    mgr._sandboxes = {}
    return mgr


def _handle_over(fake):
    return k8s_sandbox.SandboxHandle(
        sandbox_id=fake.sandbox_id,
        session_id="sess-1",
        git_scope="current_project",
        _backend=fake,
    )


# ---------------------------------------------------------------------------
# Fix #1: write_file stages via the SDK upload endpoint + mv, so it is NOT
# capped by Linux MAX_ARG_STRLEN (~96 KB once base64-expanded). Large text and
# binary payloads (git bundles) must round-trip exactly.
# ---------------------------------------------------------------------------


class TestWriteFileLargePayload:
    @pytest.mark.asyncio
    async def test_large_text_round_trips(self):
        mgr, fake = _bare_manager(), FakeSandbox()
        handle = _handle_over(fake)
        content = "x" * 200_000  # >> the old ~96 KB argv ceiling
        await mgr.write_file(handle, "big.txt", content)
        assert await mgr.read_file(handle, "big.txt") == content

    @pytest.mark.asyncio
    async def test_payload_never_passes_through_argv(self):
        # The whole point of the fix: content goes over files.write, never as a
        # command argument. No run() invocation may contain the payload.
        mgr, fake = _bare_manager(), FakeSandbox()
        handle = _handle_over(fake)
        content = "y" * 200_000
        await mgr.write_file(handle, "big.txt", content)
        assert all(content not in cmd for cmd in fake.run_log)

    @pytest.mark.asyncio
    async def test_binary_bytes_round_trip(self):
        # Bundles live at absolute /tmp/... paths in production; read_file_bytes
        # now pulls them over the SDK's native binary download (files.read),
        # not a base64 shell hop.
        mgr, fake = _bare_manager(), FakeSandbox()
        handle = _handle_over(fake)
        blob = bytes(range(256)) * 512  # 128 KB of non-UTF-8 bytes (git bundle)
        await mgr.write_file(handle, "/tmp/bundle.bundle", blob)
        assert await mgr.read_file_bytes(handle, "/tmp/bundle.bundle") == blob

    @pytest.mark.asyncio
    async def test_writes_into_subdirectory(self):
        mgr, fake = _bare_manager(), FakeSandbox()
        handle = _handle_over(fake)
        await mgr.write_file(handle, "src/deep/a.txt", "hello")
        assert await mgr.read_file(handle, "src/deep/a.txt") == "hello"

    @pytest.mark.asyncio
    async def test_failed_move_cleans_up_temp(self):
        # If mv fails, write_file must raise AND leave no staged temp behind.
        mgr = _bare_manager()

        class _MvFails(FakeSandbox):
            def _run_simple(self, argv, cwd):
                if argv and argv[0] == "mv":
                    return 1, "", "mv: cannot move", cwd
                return super()._run_simple(argv, cwd)

        fake = _MvFails()
        handle = _handle_over(fake)
        with pytest.raises(RuntimeError, match="write_file to bad.txt failed"):
            await mgr.write_file(handle, "bad.txt", "data")
        # The staged /app/*.tmp must have been rm -f'd on the failure path.
        assert not [p for p in fake._fs if p.startswith("/app/")]

    @pytest.mark.asyncio
    async def test_upload_timeout_cleans_up_temp(self):
        # Fix #4: even if the upload trips its own timeout after staging bytes,
        # write_file raises AND the finally must clear the staged temp.
        mgr = _bare_manager()

        class _StageThenTimeoutFiles(_FakeFiles):
            async def write(self, name, content):
                await super().write(name, content)  # stage the temp
                raise asyncio.TimeoutError()

        fake = FakeSandbox()
        fake.files = _StageThenTimeoutFiles(fake._fs)
        handle = _handle_over(fake)
        with pytest.raises(RuntimeError, match="upload timed out"):
            await mgr.write_file(handle, "slow.txt", "data")
        assert not [p for p in fake._fs if p.startswith("/app/")]

    @pytest.mark.asyncio
    async def test_outer_cancellation_still_cleans_up_temp(self):
        # Fix #4: v1/tools.py wraps write_file in asyncio.wait_for. If that outer
        # bound fires mid-move, the shielded cleanup must still run to completion
        # so no /app/.druppie-write-*.tmp is orphaned.
        mgr = _bare_manager()

        class _SlowMv(FakeSandbox):
            async def run(self, cmd, timeout=None):
                # Only the mv stalls; the shielded rm (no "mv -f") stays fast.
                if "mv -f" in cmd:
                    await asyncio.sleep(5)
                return await super().run(cmd, timeout)

        fake = _SlowMv()
        handle = _handle_over(fake)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                mgr.write_file(handle, "slow.txt", "data"), timeout=0.1
            )
        # Let the detached, shielded rm task finish, then assert no temp leaked.
        await asyncio.sleep(0.05)
        assert not [p for p in fake._fs if p.startswith("/app/")]


# ---------------------------------------------------------------------------
# Fix #2: a failed host-side clone must NOT hand back a sandbox over an empty
# workspace. create() terminates the claim and re-raises; nothing is tracked.
# ---------------------------------------------------------------------------


class TestCreateCloneFailure:
    @pytest.mark.asyncio
    async def test_clone_failure_terminates_and_raises(self):
        mgr, fake = _bare_manager(), FakeSandbox("sb-clonefail")

        class _Client:
            async def create_sandbox(self, warmpool, namespace, labels):
                return fake

        mgr.client = _Client()

        async def _boom(*a, **k):
            raise RuntimeError("clone exploded")

        mgr._host_side_clone = _boom

        with pytest.raises(RuntimeError, match="clone exploded"):
            await mgr.create(
                "sess-1", "current_project",
                repo_clone_url="https://user:tok@gitea/org/repo.git",
                branch="main",
            )
        assert fake.terminated is True
        assert mgr._sandboxes == {}  # claim not leaked into tracking

    @pytest.mark.asyncio
    async def test_successful_create_tracks_sandbox(self):
        mgr, fake = _bare_manager(), FakeSandbox("sb-ok")

        class _Client:
            async def create_sandbox(self, warmpool, namespace, labels):
                return fake

        mgr.client = _Client()

        async def _ok(*a, **k):
            return None

        mgr._host_side_clone = _ok

        handle = await mgr.create(
            "sess-1", "current_project",
            repo_clone_url="https://user:tok@gitea/org/repo.git",
            branch="dev",
        )
        assert handle.sandbox_id == "sb-ok"
        assert handle.branch == "dev"
        assert mgr._sandboxes["sess-1::current_project"] is fake
        assert fake.terminated is False

    @pytest.mark.asyncio
    async def test_readiness_timeout_terminates_and_raises(self):
        # Fix #3: the readiness gate runs before clone/git-config. If the pod's
        # runtime never answers, create() must terminate the claim and raise
        # rather than hand back a handle to a not-ready sandbox.
        mgr, fake = _bare_manager(), FakeSandbox("sb-notready")

        class _Client:
            async def create_sandbox(self, warmpool, namespace, labels):
                return fake

        mgr.client = _Client()

        async def _never_ready(sandbox, sandbox_id, timeout=60.0):
            raise TimeoutError("sandbox %s not ready" % sandbox_id)

        mgr._wait_until_ready = _never_ready

        clone_called = {"n": 0}

        async def _clone(*a, **k):
            clone_called["n"] += 1

        mgr._host_side_clone = _clone

        with pytest.raises(TimeoutError, match="not ready"):
            await mgr.create(
                "sess-1", "current_project",
                repo_clone_url="https://user:tok@gitea/org/repo.git",
            )
        assert fake.terminated is True
        assert mgr._sandboxes == {}          # claim not leaked into tracking
        assert clone_called["n"] == 0        # gate fires before the clone


# ---------------------------------------------------------------------------
# Fix #3: _wait_until_ready is the real readiness barrier — it replaces the
# SDK's neutralised wait_for_sandbox_ready. It must return once the runtime
# answers, tolerate transient not-ready errors with backoff, and raise on
# timeout so create() can reclaim the sandbox.
# ---------------------------------------------------------------------------


class TestWaitUntilReady:
    @pytest.mark.asyncio
    async def test_returns_when_runtime_answers(self):
        mgr, fake = _bare_manager(), FakeSandbox()
        # A healthy FakeSandbox answers "echo ok" with exit 0 immediately.
        await mgr._wait_until_ready(fake, "sb-ok", timeout=5)

    @pytest.mark.asyncio
    async def test_retries_transient_errors_then_succeeds(self):
        mgr = _bare_manager()

        class _ReadyAfter(FakeSandbox):
            def __init__(self, fail_times):
                super().__init__()
                self._fail = fail_times

            async def run(self, cmd, timeout=None):
                if self._fail > 0:
                    self._fail -= 1
                    raise ConnectionError("pod warming up")
                return await super().run(cmd, timeout)

        fake = _ReadyAfter(fail_times=2)
        await mgr._wait_until_ready(fake, "sb-warming", timeout=10)
        assert fake._fail == 0  # both transient failures were retried

    @pytest.mark.asyncio
    async def test_raises_timeout_when_never_ready(self):
        mgr = _bare_manager()

        class _NeverReady(FakeSandbox):
            async def run(self, cmd, timeout=None):
                self.run_log.append(cmd)
                return _CmdResult(1, "", "not ready")

        fake = _NeverReady()
        with pytest.raises(TimeoutError, match="not ready"):
            await mgr._wait_until_ready(fake, "sb-dead", timeout=0.1)


# ---------------------------------------------------------------------------
# Fix #5: read_file_bytes now uses the SDK's native binary download
# (files.read, allow_unsafe_paths=True) instead of a base64 shell hop. Raw
# bytes round-trip and download failures surface as a clear RuntimeError.
# ---------------------------------------------------------------------------


class TestReadFileBytesNativeDownload:
    @pytest.mark.asyncio
    async def test_reads_absolute_path_verbatim(self):
        mgr, fake = _bare_manager(), FakeSandbox()
        handle = _handle_over(fake)
        blob = bytes(range(256))
        fake._fs["/tmp/x.bundle"] = blob  # placed as git would, at an abs path
        assert await mgr.read_file_bytes(handle, "/tmp/x.bundle") == blob

    @pytest.mark.asyncio
    async def test_passes_allow_unsafe_paths(self):
        # The absolute path must reach files.read verbatim (allow_unsafe_paths),
        # not be rewritten under /app by the SDK's default sanitiser.
        mgr, fake = _bare_manager(), FakeSandbox()
        handle = _handle_over(fake)
        captured = {}

        async def _read(name, timeout=60, allow_unsafe_paths=False):
            captured["name"] = name
            captured["allow_unsafe_paths"] = allow_unsafe_paths
            return b"data"

        fake.files.read = _read
        await mgr.read_file_bytes(handle, "/tmp/x.bundle")
        assert captured["name"] == "/tmp/x.bundle"
        assert captured["allow_unsafe_paths"] is True

    @pytest.mark.asyncio
    async def test_missing_file_raises_runtimeerror(self):
        mgr, fake = _bare_manager(), FakeSandbox()
        handle = _handle_over(fake)
        with pytest.raises(RuntimeError, match="read_file_bytes from /tmp/missing"):
            await mgr.read_file_bytes(handle, "/tmp/missing.bundle")


# ---------------------------------------------------------------------------
# Source-level regression guards for cluster-only code paths that the fake
# shell can't reach (the extract runs inside _host_side_clone against a real
# clone). Cheap pins so the fixes aren't silently reverted.
# ---------------------------------------------------------------------------


class TestFixRegressionGuards:
    def _source(self):
        return _K8S_SANDBOX_FILE.read_text(encoding="utf-8")

    def test_write_file_uses_upload_not_base64_argv(self):
        wf = self._source().split("async def write_file")[1].split("\n    async def ")[0]
        # Split docstring off from code so a base64 mention in the rationale
        # doesn't mask a base64 call sneaking back into the body.
        code = wf.split('"""', 2)[-1]
        assert "files.write" in code
        assert "mv -f" in code
        assert "base64" not in code  # the old, size-capped path is gone

    def test_host_side_clone_wipe_uses_and_not_semicolon(self):
        # Fix #3: '&&' so a failed wipe doesn't overlay the new repo on stale
        # files from a recycled warm-pool sandbox.
        assert "find /workspace -mindepth 1 -delete && tar -xf" in self._source()

    def test_read_file_bytes_uses_native_download_not_base64(self):
        # Fix #5: read_file_bytes moved off the base64 shell hop onto the SDK's
        # native binary download. Split the docstring off so the rationale's
        # prose doesn't mask a base64/shell call sneaking back into the body.
        rb = (
            self._source()
            .split("async def read_file_bytes")[1]
            .split("\n    async def ")[0]
        )
        code = rb.split('"""', 2)[-1]
        assert "files.read" in code
        assert "allow_unsafe_paths=True" in code
        assert "base64" not in code
        assert "self.exec" not in code  # no shell hop

    def test_write_file_cleanup_is_shielded(self):
        # Fix #4: the staged-temp cleanup must survive an outer cancellation, so
        # it runs under asyncio.shield inside a finally.
        wf = (
            self._source()
            .split("async def write_file")[1]
            .split("\n    async def ")[0]
        )
        assert "finally:" in wf
        assert "asyncio.shield" in wf

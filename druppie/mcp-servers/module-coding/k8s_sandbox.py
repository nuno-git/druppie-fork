"""
K8s Sandbox Manager — abstraction layer over the agent-sandbox SDK.

Replaces Docker-based sandbox management with Kubernetes-native sandboxes
managed by the agent-sandbox controller (kubernetes-sigs/agent-sandbox).

The interface mirrors the Docker-based functions in module-coding/tools.py:
  - create sandbox (was: docker run)
  - exec command (was: docker exec)
  - read/write files (was: docker exec cat/tee)
  - destroy sandbox (was: docker rm -f)

Two backends are supported:
  1. "k8s"    — uses agent-sandbox SDK (production, gVisor isolation)
  2. "docker" — uses Docker CLI (local dev, backward compatible)

The backend is selected via DRUPPIE_SANDBOX_MODE env var.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import posixpath
import shlex
import shutil
import tarfile
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

logger = logging.getLogger(__name__)

# In k8s mode SANDBOX_NAMESPACE / SANDBOX_WARMPOOL MUST come from the
# environment. The Helm chart's ConfigMap injects the real, per-instance values
# (SANDBOX_NAMESPACE="{instance}-sandbox", SANDBOX_WARMPOOL="{instance}-warmpool"
# — see helm/druppie/templates/configmap.yaml). The fallbacks below match no
# chart-created resource; they exist only so the module imports outside the
# cluster. If k8s mode ever runs with these fallbacks, create_sandbox and the
# orphan reaper would target a namespace that does not exist, so __init__ warns
# loudly rather than fail silently. See docs/SANDBOX.md "Known limitations".
_NAMESPACE_FALLBACK = "sandbox-runtime"
_WARMPOOL_FALLBACK = "agent-coding-warmpool"

SANDBOX_MODE = os.getenv("DRUPPIE_SANDBOX_MODE", "docker")  # "k8s" or "docker"
SANDBOX_NAMESPACE = os.getenv("SANDBOX_NAMESPACE", _NAMESPACE_FALLBACK)
SANDBOX_WARMPOOL = os.getenv("SANDBOX_WARMPOOL", _WARMPOOL_FALLBACK)


def _strip_credentials(url: str) -> str:
    """Remove any user:password@ from a URL, leaving scheme://host[:port]/path.

    Used to rewrite the sandbox's origin URL after an authenticated clone so
    no token persists in .git/config (sandboxes must hold no git credentials).
    """
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    return urlunsplit(parts._replace(netloc=host))


@dataclass
class SandboxHandle:
    """Opaque handle representing an active sandbox. Passed back to tools.py."""
    sandbox_id: str
    session_id: str
    git_scope: str
    branch: str = "main"
    created_at: float = field(default_factory=time.time)
    _backend: object = None  # backend-specific object (SDK sandbox or docker container)


class K8sSandboxManager:
    """Manages agent sandboxes via the agent-sandbox CRD + Python SDK."""

    def __init__(self):
        try:
            from k8s_agent_sandbox import AsyncSandboxClient
            from k8s_agent_sandbox.models import SandboxInClusterConnectionConfig
        except ImportError:
            raise RuntimeError(
                "k8s-agent-sandbox package not installed. "
                "Install with: pip install k8s-agent-sandbox[async]"
            )

        config = SandboxInClusterConnectionConfig()
        self.client = AsyncSandboxClient(connection_config=config)
        self._sandboxes: dict[str, object] = {}

        # KNOWN DEBT (see docs/SANDBOX.md "Known limitations"): neutralise the
        # SDK's wait_for_sandbox_ready. In the warm-pool adoption race the
        # operator deletes the transient Sandbox resource before the SDK can
        # establish its watch, so the SDK wait raises/hangs even though the pod
        # is coming up healthy. Replacing it with a no-op unblocks create_sandbox;
        # readiness is NOT dropped — create() re-establishes it with a command
        # probe (_wait_until_ready) that depends on no SDK watch internals. This
        # monkeypatch is fragile: a k8s-agent-sandbox upgrade can change the
        # method's signature and it must be re-verified then.
        async def _patched_wait(sandbox_id, namespace, timeout):
            return None
        self.client.k8s_helper.wait_for_sandbox_ready = _patched_wait

        logger.info("K8sSandboxManager initialized (namespace=%s, warmpool=%s)",
                     SANDBOX_NAMESPACE, SANDBOX_WARMPOOL)

        # Guard against the misleading import-time fallbacks (see module top).
        # In-cluster these are always provided by the Helm ConfigMap; if we see
        # the fallback here, sandbox creation and orphan cleanup will silently
        # target a non-existent namespace, so make the misconfiguration visible.
        if SANDBOX_NAMESPACE == _NAMESPACE_FALLBACK or SANDBOX_WARMPOOL == _WARMPOOL_FALLBACK:
            logger.warning(
                "K8sSandboxManager: SANDBOX_NAMESPACE/SANDBOX_WARMPOOL are using "
                "non-chart fallback values (%s / %s). In-cluster these MUST come "
                "from the Helm ConfigMap ('{instance}-sandbox' / "
                "'{instance}-warmpool'); with the fallback, create_sandbox and the "
                "orphan reaper target a namespace that does not exist. "
                "Set both env vars.",
                SANDBOX_NAMESPACE, SANDBOX_WARMPOOL,
            )

    async def create(
        self,
        session_id: str,
        git_scope: str,
        repo_clone_url: Optional[str] = None,
        branch: str = "main",
    ) -> SandboxHandle:
        """Claim a sandbox from the warm pool and optionally clone a repo."""
        labels = {
            "session-id": session_id[:63],
            "git-scope": git_scope,
        }

        sandbox = await asyncio.wait_for(
            self.client.create_sandbox(
                warmpool=SANDBOX_WARMPOOL,
                namespace=SANDBOX_NAMESPACE,
                labels=labels,
            ),
            timeout=120,
        )
        sandbox_id = sandbox.sandbox_id
        logger.info("Sandbox claimed: %s (session=%s, scope=%s)",
                     sandbox_id, session_id, git_scope)

        # The SDK's readiness wait is neutralised in __init__ (warm-pool
        # adoption race), so gate readiness ourselves BEFORE cloning / git
        # config — otherwise those steps race a pod whose runtime is not yet
        # answering and fail only on their own timeouts. On timeout terminate
        # the just-claimed sandbox (same pattern as the clone-failure path
        # below) so the claim does not leak, then surface a clear error.
        try:
            await self._wait_until_ready(sandbox, sandbox_id)
        except Exception:
            try:
                await asyncio.wait_for(sandbox.terminate(), timeout=30)
            except Exception:
                logger.warning(
                    "Failed to terminate sandbox %s after readiness timeout",
                    sandbox_id,
                )
            raise

        if repo_clone_url:
            try:
                await self._host_side_clone(
                    sandbox, sandbox_id, repo_clone_url, branch
                )
            except Exception:
                # Clone failed — do NOT hand back a sandbox over an empty
                # workspace. The agent would otherwise operate on nothing and
                # only discover it at push time. Release the claim so it does
                # not leak, then propagate: _resolve_container retries once and
                # ultimately surfaces a clear error to the agent.
                try:
                    await asyncio.wait_for(sandbox.terminate(), timeout=30)
                except Exception:
                    logger.warning(
                        "Failed to terminate sandbox %s after clone failure",
                        sandbox_id,
                    )
                raise

        try:
            await asyncio.wait_for(
                sandbox.commands.run("bash -c " + shlex.quote("git config --global --add safe.directory /workspace")),
                timeout=15,
            )
        except Exception as e:
            # Best-effort git config: a failure here must not abort create() and
            # leak the already-claimed sandbox, which is not tracked in
            # self._sandboxes until below (so destroy() could not reach it).
            logger.warning("Sandbox %s: git config safe.directory failed: %s", sandbox_id, e)

        try:
            await asyncio.wait_for(
                sandbox.commands.run("bash -c " + shlex.quote("git -C /workspace config user.email 'agent@druppie.local'")),
                timeout=15,
            )
        except Exception as e:
            logger.warning("Sandbox %s: git config user.email failed: %s", sandbox_id, e)

        try:
            await asyncio.wait_for(
                sandbox.commands.run("bash -c " + shlex.quote("git -C /workspace config user.name 'Druppie Agent'")),
                timeout=15,
            )
        except Exception as e:
            logger.warning("Sandbox %s: git config user.name failed: %s", sandbox_id, e)

        self._sandboxes[f"{session_id}::{git_scope}"] = sandbox
        return SandboxHandle(
            sandbox_id=sandbox_id,
            session_id=session_id,
            git_scope=git_scope,
            branch=branch,
            _backend=sandbox,
        )

    async def _wait_until_ready(
        self, sandbox, sandbox_id: str, timeout: float = 60.0
    ) -> None:
        """Block until the sandbox runtime answers a trivial command.

        The SDK's own readiness wait is neutralised in __init__ (warm-pool
        adoption race), so readiness is gated here instead: poll
        ``echo ok`` with exponential backoff until it exits 0 or ``timeout``
        seconds elapse. Depends on no SDK watch internals — just the same
        command channel every later step uses. Raises ``TimeoutError`` on
        expiry so create() can terminate the just-claimed sandbox rather than
        hand back a handle to a pod whose runtime never came up.
        """
        deadline = time.monotonic() + timeout
        delay = 0.5
        last_err: Optional[Exception] = None
        while True:
            try:
                result = await asyncio.wait_for(
                    sandbox.commands.run("echo ok", timeout=5),
                    timeout=10,
                )
                if result.exit_code == 0:
                    return
                last_err = RuntimeError(
                    "readiness probe exited %s" % result.exit_code
                )
            except asyncio.TimeoutError:
                last_err = TimeoutError("readiness probe timed out")
            except Exception as e:  # not-yet-ready runtimes surface transient errors
                last_err = e
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    "sandbox %s not ready after %.0fs: %s"
                    % (sandbox_id, timeout, last_err)
                )
            await asyncio.sleep(delay)
            delay = min(delay * 2, 5.0)

    async def _host_side_clone(
        self,
        sandbox,
        sandbox_id: str,
        repo_clone_url: str,
        branch: str,
    ) -> None:
        """Clone the repo on the module-coding host and ship it into the sandbox.

        The gVisor sandbox cannot reach in-cluster services (Gitea is exposed as
        a ClusterIP, which gVisor's userspace netstack cannot reach), so the
        clone runs here on the host, is tarred in memory, uploaded to the sandbox
        as ``repo.tar`` (relative name -> ``/app/repo.tar``; the SDK upload
        endpoint 500s on absolute paths) and extracted into ``/workspace``. The
        origin URL is then rewritten to a credential-stripped form so no token
        is left in ``/workspace/.git/config``; push/fetch still work because the
        host side (``push_changes``) exchanges git bundles with credentials.

        Raises RuntimeError on any fatal failure (clone, upload, extract or
        verify) so the caller discards the claim instead of returning a handle
        over an empty workspace. Origin rewrite and sslVerify config are
        best-effort (the repo is already present) and only warn on timeout.
        """
        tmpdir = await asyncio.to_thread(tempfile.mkdtemp, prefix="sandbox-clone-")
        try:
            clone_cmd = (
                "git", "-c", "http.sslVerify=false", "clone", "--depth", "50",
                "--branch", branch,
                repo_clone_url, tmpdir,
            )
            proc = await asyncio.create_subprocess_exec(
                *clone_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout_b, stderr_b = await asyncio.wait_for(
                    proc.communicate(), timeout=120
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise RuntimeError("host-side git clone timed out (120s)")

            if proc.returncode != 0:
                detail = (stderr_b or stdout_b).decode(errors="replace")[:200]
                raise RuntimeError(
                    "host-side git clone failed (rc=%s): %s"
                    % (proc.returncode, detail)
                )

            # Build an in-memory tar of the cloned tree (incl. .git) and upload.
            buf = io.BytesIO()

            def _build_tar() -> None:
                with tarfile.open(fileobj=buf, mode="w") as tar:
                    tar.add(tmpdir, arcname=".")

            await asyncio.to_thread(_build_tar)
            # Relative name -> /app/repo.tar inside the sandbox.
            try:
                await asyncio.wait_for(
                    sandbox.files.write("repo.tar", buf.getvalue()),
                    timeout=30,
                )
            except asyncio.TimeoutError:
                raise RuntimeError("host-side clone: repo.tar upload timed out")
            # /workspace is a PVC mount; a recycled warm-pool sandbox may still
            # hold the previous session's files, so wipe it before extracting.
            # Use '&&' (not ';') between wipe and extract so a failed wipe does
            # not silently overlay the new repo on a prior session's leftovers.
            extract = "find /workspace -mindepth 1 -delete && tar -xf /app/repo.tar -C /workspace && rm -f /app/repo.tar"
            try:
                eres = await asyncio.wait_for(
                    sandbox.commands.run("bash -c " + shlex.quote(extract)),
                    timeout=60,
                )
            except asyncio.TimeoutError:
                raise RuntimeError("host-side clone: tar extract timed out")
            if eres.exit_code != 0:
                raise RuntimeError(
                    "host-side clone: wipe/extract failed: %s"
                    % (eres.stderr or eres.stdout)[:200]
                )

            # Verify the repo landed so clone success/failure is observable.
            verify = "git -C /workspace rev-parse --is-inside-work-tree"
            try:
                vres = await asyncio.wait_for(
                    sandbox.commands.run("bash -c " + shlex.quote(verify)),
                    timeout=15,
                )
            except asyncio.TimeoutError:
                raise RuntimeError("host-side clone: git verify timed out")
            if vres.exit_code != 0:
                raise RuntimeError(
                    "/workspace is not a git repo after host-side clone "
                    "(extract may have failed): %s"
                    % (vres.stderr or vres.stdout)[:200]
                )

            # Rewrite origin to the credential-stripped URL (set-url if the
            # clone created one, else add) so no token persists in .git/config.
            public_url = _strip_credentials(repo_clone_url)
            set_origin = (
                "git -C /workspace remote set-url origin "
                + shlex.quote(public_url)
                + " || git -C /workspace remote add origin "
                + shlex.quote(public_url)
                + " || true"
            )
            try:
                await asyncio.wait_for(
                    sandbox.commands.run("bash -c " + shlex.quote(set_origin)),
                    timeout=15,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Host-side clone: set-origin timed out for sandbox %s",
                    sandbox_id,
                )

            # Corporate Gitea uses a self-signed/internal CA cert — disable SSL
            # verification so git fetch/pull/push inside the sandbox work.
            try:
                await asyncio.wait_for(
                    sandbox.commands.run("bash -c " + shlex.quote("git -C /workspace config http.sslVerify false")),
                    timeout=15,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Host-side clone: git config http.sslVerify timed out for sandbox %s",
                    sandbox_id,
                )

            logger.info(
                "Host-side clone OK for sandbox %s (branch=%s)", sandbox_id, branch
            )
        except Exception as e:
            logger.error(
                "Host-side clone failed for sandbox %s: %s", sandbox_id, e
            )
            raise
        finally:
            await asyncio.to_thread(shutil.rmtree, tmpdir, ignore_errors=True)

    async def exec(self, handle: SandboxHandle, command: list[str] | str,
                   timeout: int = 60) -> tuple[int, str, str]:
        """Execute a command in the sandbox. Returns (exit_code, stdout, stderr).

        The agent-sandbox runtime tokenizes the command string with shlex and
        execs the first token — it does NOT invoke a shell — so shell operators
        (&&, pipes, redirects) are ignored unless we wrap the command in
        ``bash -c``. tools.py passes either a tokenized list (simple command) or
        ``["bash", "-c", <shellstring>]`` (from _exec_shell); we normalise both
        to a single shell string and wrap once.

        Commands run with ``/workspace`` as the working directory: the sandbox
        image's WORKDIR is ``/app`` (the agent-sandbox runtime server must live
        there), but Druppie's tools — and docker-mode, whose image WORKDIR is
        ``/workspace`` — assume commands run in the repo root (e.g. push_changes
        invokes bare ``git status`` / ``git bundle create`` with no ``-C``). We
        prepend ``cd /workspace &&`` so k8s matches docker semantics. ``/workspace``
        always exists (the sandbox image creates it).
        """
        if isinstance(command, list):
            if len(command) == 3 and command[0] == "bash" and command[1] == "-c":
                shell_str = command[2]
            else:
                shell_str = shlex.join(command)
        else:
            shell_str = command
        shell_str = "cd /workspace && " + shell_str
        wrapped = "bash -c " + shlex.quote(shell_str)
        try:
            result = await asyncio.wait_for(
                handle._backend.commands.run(wrapped, timeout=timeout),
                timeout=timeout + 10,
            )
        except asyncio.TimeoutError:
            return (-1, "", f"Command timed out after {timeout}s")
        return result.exit_code, result.stdout, result.stderr

    async def read_file(self, handle: SandboxHandle, path: str) -> str:
        """Read a (text) file from the sandbox."""
        rc, out, _ = await self.exec(handle, "cat " + shlex.quote(path))
        return out

    async def read_file_bytes(self, handle: SandboxHandle, path: str) -> bytes:
        """Read a binary file from the sandbox (e.g. a git bundle).

        Uses the SDK's native binary download (``sandbox.files.read`` -> the
        runtime's ``GET download/<path>`` endpoint), the symmetric twin of the
        ``files.write`` upload write_file relies on. It returns raw bytes with
        no base64 shell hop, so large/binary payloads (the git bundles from
        git_fetch/git_pull) round-trip exactly instead of being corrupted by
        ``exec``'s text-decoded ``str`` stdout.

        ``allow_unsafe_paths=True`` passes the caller's path through verbatim:
        the SDK's default sanitiser strips a leading ``/`` and rejects ``..``,
        which would rewrite an absolute path like ``/tmp/x.bundle`` to a
        relative one resolved under ``/app`` — the wrong file. The paths read
        here are internal, code-generated bundle paths (``/tmp/...``), never
        user-controlled, so bypassing the sanitiser is safe.
        """
        sandbox = handle._backend
        try:
            return await sandbox.files.read(path, allow_unsafe_paths=True)
        except Exception as e:
            raise RuntimeError(
                "read_file_bytes from %s failed: %s" % (path, e)
            ) from e

    async def write_file(self, handle: SandboxHandle, path: str,
                         content: str | bytes) -> None:
        """Write a file into the sandbox (text or binary).

        Content is staged via the SDK's files.write upload endpoint under a
        RELATIVE temp name (absolute paths 500 on that endpoint; a relative
        name lands at ``/app/<name>``) and then moved into place. The previous
        approach piped base64 through ``bash -c``, but that passes the whole
        payload as a single argv entry, which fails (execve ``E2BIG``) for
        content larger than ~96 KB (Linux ``MAX_ARG_STRLEN`` caps one argument
        at 128 KB, and base64 adds ~33%). The upload endpoint has no such
        limit — it is the same path used to ship the repo tar in — so large
        files and binary bundles (git_fetch/git_pull) now round-trip correctly.
        """
        if isinstance(content, str):
            content = content.encode("utf-8")
        sandbox = handle._backend
        tmp_name = ".druppie-write-%s.tmp" % uuid.uuid4().hex
        tmp_abs = "/app/" + tmp_name
        moved = False
        try:
            try:
                await asyncio.wait_for(sandbox.files.write(tmp_name, content), timeout=60)
            except asyncio.TimeoutError:
                raise RuntimeError("write_file to %s failed: upload timed out" % path)
            parent = posixpath.dirname(path) or "/"
            mv_cmd = (
                "mkdir -p " + shlex.quote(parent)
                + " && mv -f " + shlex.quote(tmp_abs) + " " + shlex.quote(path)
            )
            rc, _, err = await self.exec(handle, mv_cmd)
            if rc != 0:
                raise RuntimeError("write_file to %s failed: %s" % (path, err.strip()))
            moved = True
        finally:
            # Guarantee the staged temp never leaks: clean it up on mv failure,
            # on upload timeout, AND on an outer cancellation (v1/tools.py wraps
            # this call in asyncio.wait_for). A successful mv already consumed
            # the temp, so skip in that case. The cleanup exec is shielded so an
            # outer wait_for cancellation cannot abort the cleanup itself and
            # orphan a /app/.druppie-write-*.tmp forever — the rm runs to
            # completion even while the CancelledError propagates out of here.
            if not moved:
                try:
                    await asyncio.shield(
                        self.exec(handle, "rm -f " + shlex.quote(tmp_abs))
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.warning(
                        "write_file: failed to clean up staged temp %s", tmp_abs
                    )

    async def file_exists(self, handle: SandboxHandle, path: str) -> bool:
        """Check if a file exists in the sandbox."""
        rc, out, _ = await self.exec(
            handle, "test -f %s && echo yes || echo no" % shlex.quote(path)
        )
        return "yes" in out

    async def destroy(self, handle: SandboxHandle) -> None:
        """Terminate the sandbox and clean up."""
        key = f"{handle.session_id}::{handle.git_scope}"
        sandbox = self._sandboxes.pop(key, None)
        if sandbox:
            try:
                await asyncio.wait_for(sandbox.terminate(), timeout=30)
                logger.info("Sandbox destroyed: %s", handle.sandbox_id)
            except asyncio.TimeoutError:
                logger.warning("Sandbox %s: terminate timed out", handle.sandbox_id)
            except Exception as e:
                logger.warning("Failed to destroy sandbox %s: %s",
                               handle.sandbox_id, e)

    async def is_alive(self, handle: SandboxHandle) -> bool:
        """Check if the sandbox is still running."""
        try:
            result = await asyncio.wait_for(
                handle._backend.commands.run("echo ok", timeout=5),
                timeout=10,
            )
            return result.exit_code == 0
        except (asyncio.TimeoutError, Exception):
            return False

    async def destroy_all_for_session(self, session_id: str) -> int:
        """Destroy all sandboxes for a session. Returns count destroyed."""
        count = 0
        keys_to_remove = [
            k for k in self._sandboxes if k.startswith(f"{session_id}::")
        ]
        for key in keys_to_remove:
            sandbox = self._sandboxes.pop(key)
            try:
                await asyncio.wait_for(sandbox.terminate(), timeout=30)
                count += 1
            except (asyncio.TimeoutError, Exception):
                pass
        return count

    async def cleanup_orphan_claims(
        self, known_keys: set[str], min_age_seconds: int = 300
    ) -> int:
        """Reap SandboxClaims in the configured SANDBOX_NAMESPACE this process doesn't track.

        After a restart the in-memory ``sandbox_containers`` / ``_sandboxes``
        dicts are empty, so leftover SandboxClaims from the previous run — or
        leaked by a recreate-without-destroy — are orphans and pin cluster
        resources (each reserves a pod). This lists claims (labelled with
        session-id / git-scope) and deletes any whose ``session::scope`` key is
        not in ``known_keys`` and which are older than ``min_age_seconds`` (the
        age gate spares fresh claims that may be mid-create in another call).
        Single-replica assumption holds (module-coding replicas=1).

        Uses the in-cluster ServiceAccount; RBAC already grants list/delete on
        sandboxclaims in SANDBOX_NAMESPACE (helm agent-sandbox/rbac.yaml).
        """

        def _sweep() -> int:
            import datetime  # local: only needed for this rarely-run sweep
            from kubernetes import client as k8s_client
            from kubernetes.config import load_incluster_config

            try:
                load_incluster_config()
            except Exception as e:
                logger.warning("orphan_sweep: no in-cluster config: %s", e)
                return 0

            api = k8s_client.CustomObjectsApi()
            group, version, plural = (
                "extensions.agents.x-k8s.io", "v1beta1", "sandboxclaims",
            )
            try:
                res = api.list_namespaced_custom_object(
                    group=group, version=version,
                    namespace=SANDBOX_NAMESPACE, plural=plural,
                )
            except Exception as e:
                logger.warning("orphan_sweep: list sandboxclaims failed: %s", e)
                return 0

            now = time.time()
            deleted = 0
            for item in res.get("items", []):
                meta = item.get("metadata", {}) or {}
                name = meta.get("name", "")
                labels = meta.get("labels", {}) or {}
                key = "%s::%s" % (labels.get("session-id", ""), labels.get("git-scope", ""))
                if key in known_keys:
                    continue  # this process still tracks it
                created = meta.get("creationTimestamp")
                if created:
                    try:
                        ct = datetime.datetime.fromisoformat(created.replace("Z", "+00:00"))
                        if now - ct.timestamp() < min_age_seconds:
                            continue
                    except Exception:
                        continue  # can't parse age -> don't risk deleting
                try:
                    api.delete_namespaced_custom_object(
                        group=group, version=version,
                        namespace=SANDBOX_NAMESPACE, plural=plural, name=name,
                    )
                    deleted += 1
                    logger.info("orphan_sweep: deleted SandboxClaim %s (%s)", name, key)
                except Exception as e:
                    logger.warning("orphan_sweep: delete %s failed: %s", name, e)
            return deleted

        return await asyncio.to_thread(_sweep)


def get_sandbox_manager():
    """Factory: returns the appropriate manager based on DRUPPIE_SANDBOX_MODE."""
    if SANDBOX_MODE == "k8s":
        return K8sSandboxManager()
    else:
        return None  # Docker mode — caller uses existing Docker CLI code

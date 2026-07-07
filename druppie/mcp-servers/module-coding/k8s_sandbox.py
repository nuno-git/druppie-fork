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
import base64
import io
import logging
import os
import shlex
import shutil
import tarfile
import tempfile
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

logger = logging.getLogger(__name__)

SANDBOX_MODE = os.getenv("DRUPPIE_SANDBOX_MODE", "docker")  # "k8s" or "docker"
SANDBOX_NAMESPACE = os.getenv("SANDBOX_NAMESPACE", "sandbox-runtime")
SANDBOX_WARMPOOL = os.getenv("SANDBOX_WARMPOOL", "agent-coding-warmpool")


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
        logger.info("K8sSandboxManager initialized (namespace=%s, warmpool=%s)",
                     SANDBOX_NAMESPACE, SANDBOX_WARMPOOL)

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

        sandbox = await self.client.create_sandbox(
            warmpool=SANDBOX_WARMPOOL,
            namespace=SANDBOX_NAMESPACE,
            labels=labels,
        )
        sandbox_id = sandbox.sandbox_id
        logger.info("Sandbox claimed: %s (session=%s, scope=%s)",
                     sandbox_id, session_id, git_scope)

        if repo_clone_url:
            # Host-side clone: the gVisor sandbox cannot reach Gitea's ClusterIP
            # (gVisor's userspace netstack bypasses Cilium service LB), so we
            # clone on the module-coding host (which can), tar the tree in
            # memory, upload it to the sandbox via the SDK files.write endpoint
            # and extract into /workspace. Works for every tier and keeps git
            # credentials out of the sandbox (origin is stripped post-extract).
            await self._host_side_clone(
                sandbox, sandbox_id, repo_clone_url, branch
            )

        await sandbox.commands.run("bash -c " + shlex.quote("git -C /workspace config user.email 'agent@druppie.local'"))
        await sandbox.commands.run("bash -c " + shlex.quote("git -C /workspace config user.name 'Druppie Agent'"))

        self._sandboxes[f"{session_id}::{git_scope}"] = sandbox
        return SandboxHandle(
            sandbox_id=sandbox_id,
            session_id=session_id,
            git_scope=git_scope,
            branch=branch,
            _backend=sandbox,
        )

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
        """
        tmpdir = await asyncio.to_thread(tempfile.mkdtemp, prefix="sandbox-clone-")
        try:
            clone_cmd = (
                "git", "clone", "--depth", "50",
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
                logger.warning(
                    "Host-side git clone timed out (120s) for sandbox %s",
                    sandbox_id,
                )
                return

            if proc.returncode != 0:
                detail = (stderr_b or stdout_b).decode(errors="replace")[:200]
                logger.warning(
                    "Host-side git clone failed (rc=%s) for sandbox %s: %s",
                    proc.returncode, sandbox_id, detail,
                )
                return

            # Build an in-memory tar of the cloned tree (incl. .git) and upload.
            buf = io.BytesIO()

            def _build_tar() -> None:
                with tarfile.open(fileobj=buf, mode="w") as tar:
                    tar.add(tmpdir, arcname=".")

            await asyncio.to_thread(_build_tar)
            # Relative name -> /app/repo.tar inside the sandbox.
            await sandbox.files.write("repo.tar", buf.getvalue())
            # /workspace is a PVC mount; a recycled warm-pool sandbox may still
            # hold the previous session's files, so wipe it before extracting.
            extract = "find /workspace -mindepth 1 -delete 2>/dev/null; tar -xf /app/repo.tar -C /workspace && rm -f /app/repo.tar"
            await sandbox.commands.run("bash -c " + shlex.quote(extract))

            # Verify the repo landed so clone success/failure is observable.
            verify = "git -C /workspace rev-parse --is-inside-work-tree"
            vres = await sandbox.commands.run("bash -c " + shlex.quote(verify))
            if vres.exit_code != 0:
                logger.error(
                    "Sandbox %s: /workspace is not a git repo after host-side "
                    "clone (extract may have failed): %s",
                    sandbox_id, (vres.stderr or vres.stdout)[:200],
                )
                return

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
            await sandbox.commands.run("bash -c " + shlex.quote(set_origin))
            logger.info(
                "Host-side clone OK for sandbox %s (branch=%s)", sandbox_id, branch
            )
        except Exception as e:
            logger.warning(
                "Host-side clone failed for sandbox %s: %s", sandbox_id, e
            )
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
        result = await handle._backend.commands.run(wrapped, timeout=timeout)
        return result.exit_code, result.stdout, result.stderr

    async def read_file(self, handle: SandboxHandle, path: str) -> str:
        """Read a (text) file from the sandbox."""
        rc, out, _ = await self.exec(handle, "cat " + shlex.quote(path))
        return out

    async def read_file_bytes(self, handle: SandboxHandle, path: str) -> bytes:
        """Read a binary file from the sandbox (e.g. a git bundle).

        ``exec`` returns stdout as ``str`` (decoded text), which corrupts binary
        content. We base64-encode inside the sandbox and decode here so the bytes
        round-trip exactly. ``base64.b64decode`` discards the newlines that the
        shell ``base64`` wrapper emits.
        """
        rc, out, err = await self.exec(handle, "base64 " + shlex.quote(path))
        if rc != 0:
            raise RuntimeError(
                "read_file_bytes from %s failed: %s" % (path, err.strip())
            )
        return base64.b64decode(out.encode("ascii"))

    async def write_file(self, handle: SandboxHandle, path: str,
                         content: str | bytes) -> None:
        """Write a file into the sandbox (text or binary).

        The SDK's files.write upload endpoint is unreliable for absolute paths
        (500s), so we pipe base64-decoded content through the shell. This
        handles arbitrary bytes without quoting/escaping issues.
        """
        if isinstance(content, str):
            content = content.encode("utf-8")
        b64 = base64.b64encode(content).decode("ascii")
        cmd = "printf %s " + shlex.quote(b64) + " | base64 -d > " + shlex.quote(path)
        rc, _, err = await self.exec(handle, cmd)
        if rc != 0:
            raise RuntimeError("write_file to %s failed: %s" % (path, err.strip()))

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
                await sandbox.terminate()
                logger.info("Sandbox destroyed: %s", handle.sandbox_id)
            except Exception as e:
                logger.warning("Failed to destroy sandbox %s: %s",
                               handle.sandbox_id, e)

    async def is_alive(self, handle: SandboxHandle) -> bool:
        """Check if the sandbox is still running."""
        try:
            result = await handle._backend.commands.run("echo ok", timeout=5)
            return result.exit_code == 0
        except Exception:
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
                await sandbox.terminate()
                count += 1
            except Exception:
                pass
        return count

    async def cleanup_orphan_claims(
        self, known_keys: set[str], min_age_seconds: int = 300
    ) -> int:
        """Reap SandboxClaims in sandbox-runtime this process doesn't track.

        After a restart the in-memory ``sandbox_containers`` / ``_sandboxes``
        dicts are empty, so leftover SandboxClaims from the previous run — or
        leaked by a recreate-without-destroy — are orphans and pin cluster
        resources (each reserves a pod). This lists claims (labelled with
        session-id / git-scope) and deletes any whose ``session::scope`` key is
        not in ``known_keys`` and which are older than ``min_age_seconds`` (the
        age gate spares fresh claims that may be mid-create in another call).
        Single-replica assumption holds (module-coding replicas=1).

        Uses the in-cluster ServiceAccount; RBAC already grants list/delete on
        sandboxclaims in sandbox-runtime (helm agent-sandbox/rbac.yaml).
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

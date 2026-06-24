"""Deploy service.

Triggers a Kubernetes deployment rollout when a new image is pushed to the
Harbor registry. Uses ``kubectl`` via subprocess (no python kubernetes client
dependency) — the same approach the sandbox takes with docker. A kubeconfig
path is configurable via ``KUBECONFIG_PATH``.
"""

import asyncio
import os

import structlog

logger = structlog.get_logger()

KUBECONFIG_PATH = os.getenv("KUBECONFIG_PATH", "/root/.kube/config")
KUBECTL_PATH = os.getenv("KUBECTL_PATH", "kubectl")
DEPLOY_NAMESPACE = os.getenv("DEPLOY_NAMESPACE", "druppie")


async def _run_cmd(
    cmd: list[str],
    timeout: float = 60,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    """Run a subprocess, return (returncode, stdout, stderr)."""
    logger.debug("deploy_run_cmd", cmd=" ".join(cmd))
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError(f"Command timed out after {timeout}s: {' '.join(cmd)}")
    return proc.returncode or 0, stdout.decode(), stderr.decode()


class DeployService:
    """Triggers k8s deployment rollouts via kubectl."""

    def __init__(
        self,
        kubeconfig: str | None = None,
        kubectl: str | None = None,
        namespace: str | None = None,
    ):
        self.kubeconfig = kubeconfig or KUBECONFIG_PATH
        self.kubectl = kubectl or KUBECTL_PATH
        self.namespace = namespace or DEPLOY_NAMESPACE

    def _deployment_name(self, image: str) -> str:
        """Derive a k8s deployment name from an image reference.

        Handles forms like:
          - ``harbor.druppie.io/druppie/backend:latest``
          - ``druppie/backend:latest``
          - ``backend:latest``
          - ``backend``
        Returns the last path segment with no tag/registry prefix.
        """
        name = image.rsplit(":", 1)[0]  # strip tag
        name = name.rsplit("/", 1)[-1]  # last path segment
        return name

    def _build_env(self) -> dict[str, str]:
        """Build the subprocess env, pointing KUBECONFIG at our config."""
        env = dict(os.environ)
        env["KUBECONFIG"] = self.kubeconfig
        return env

    async def trigger_deploy(
        self,
        image: str,
        tag: str | None = None,
        namespace: str | None = None,
    ) -> dict:
        """Trigger a k8s deployment rollout after a new image is pushed.

        Args:
            image: Image reference (may include registry/tag). The deployment
                name is derived from the last path segment.
            tag: Image tag (informational; logged but the rollout restart picks
                up the newest image regardless of tag).
            namespace: Override the default namespace.

        Returns:
            ``{success, message, deployment, namespace}`` dict.
        """
        ns = namespace or self.namespace
        deployment = self._deployment_name(image)

        logger.info(
            "deploy_triggered",
            image=image,
            tag=tag,
            deployment=deployment,
            namespace=ns,
        )

        cmd = [
            self.kubectl,
            "rollout",
            "restart",
            f"deployment/{deployment}",
            "-n",
            ns,
        ]

        try:
            rc, stdout, stderr = await _run_cmd(
                cmd, timeout=60, env=self._build_env()
            )
        except RuntimeError as e:
            # Includes subprocess launch failures and timeouts.
            logger.error(
                "deploy_failed",
                deployment=deployment,
                namespace=ns,
                error=str(e),
                exc_info=True,
            )
            return {
                "success": False,
                "message": str(e),
                "deployment": deployment,
                "namespace": ns,
            }

        if rc != 0:
            message = stderr.strip() or stdout.strip() or f"kubectl exit code {rc}"
            logger.warning(
                "deploy_failed",
                deployment=deployment,
                namespace=ns,
                message=message,
            )
            return {
                "success": False,
                "message": message,
                "deployment": deployment,
                "namespace": ns,
            }

        logger.info(
            "deploy_succeeded",
            deployment=deployment,
            namespace=ns,
            stdout=stdout.strip(),
        )
        return {
            "success": True,
            "message": f"Rollout restarted for deployment/{deployment} in {ns}",
            "deployment": deployment,
            "namespace": ns,
        }

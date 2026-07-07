"""Branch environment service.

Ports ``scripts/deploy-branch-env.sh`` to Python: brings up a full, isolated
Druppie stack for a git branch in its own namespace on the rijnland.dev RKE2
cluster, tracks state in the database, supports teardown, and handles CI-driven
image upgrades.

For a branch ``feature/foo`` the environment is:
    slug       feature-foo
    namespace  druppie-feature-foo
    host        druppie-feature-foo.rijnland.dev   (single label -> *.rijnland.dev cert)
    url         https://druppie-feature-foo.rijnland.dev

The wildcard ``*.rijnland.dev`` TLS secret and the Harbor image pull secret are
copied from the source namespace (default: druppie) into the new namespace,
since both are namespace-scoped. Helm then installs the chart with branch
overrides layered on top of the base + rijnland values.

kubectl/helm are invoked via ``asyncio.create_subprocess_exec`` with an argv
list (never ``shell=True``) so user-derived branch names cannot be interpreted
by a shell. The long-running deploy/teardown run as tracked background tasks.
"""

import json
import os
import re
from pathlib import Path
from uuid import UUID

import structlog

from ..api.errors import AuthorizationError, ConflictError, NotFoundError, ValidationError
from ..core.background_tasks import create_tracked_task
from ..domain import BranchEnvironmentDetail
from ..domain.branch_environment import BranchEnvironmentStatus
from ..repositories import BranchEnvironmentRepository
from .deploy_service import _run_cmd

logger = structlog.get_logger()

# -----------------------------------------------------------------------------
# Configuration (env-overridable, matching scripts/deploy-branch-env.sh defaults)
# -----------------------------------------------------------------------------
KUBECTL_PATH = os.getenv("KUBECTL_PATH", "kubectl")
HELM_PATH = os.getenv("HELM_PATH", "helm")

BRANCH_ENV_NODE = os.getenv("BRANCH_ENV_NODE", "ka-k8s-ai-workers-skbh7-d4qwl")
BRANCH_ENV_REGISTRY = os.getenv("BRANCH_ENV_REGISTRY", "harbor.rijnland.dev/druppie")
BRANCH_ENV_TLS_SRC_NS = os.getenv("BRANCH_ENV_TLS_SRC_NS", "druppie")
BRANCH_ENV_TLS_SECRET = os.getenv("BRANCH_ENV_TLS_SECRET", "druppie-tls")
BRANCH_ENV_PULL_SECRET = os.getenv("BRANCH_ENV_PULL_SECRET", "harbor-regcred")
BRANCH_ENV_PULL_SECRET_SRC_NS = os.getenv("BRANCH_ENV_PULL_SECRET_SRC_NS", "druppie")
BRANCH_ENV_HELM_TIMEOUT = os.getenv("BRANCH_ENV_HELM_TIMEOUT", "10m")


def _default_chart_path() -> str:
    """Resolve helm/druppie relative to the repo root (overridable via env).

    In-cluster the chart lives at e.g. /app/helm/druppie, set via
    BRANCH_ENV_CHART_PATH.
    """
    # services/branch_environment_service.py -> services -> druppie -> repo root
    repo_root = Path(__file__).resolve().parents[2]
    return str(repo_root / "helm" / "druppie")


BRANCH_ENV_CHART_PATH = os.getenv("BRANCH_ENV_CHART_PATH", _default_chart_path())

# Domain suffix: environments live at druppie-<slug>.<DOMAIN_SUFFIX>. Must stay a
# single label under this suffix to match the *.rijnland.dev wildcard cert.
DOMAIN_SUFFIX = "rijnland.dev"

# Modules that mount a shared RWO PVC and must co-locate with the backend.
PINNED_MODULES = ["coding", "docker", "archimate", "data_access", "filesearch", "web"]
# All deployable components (used when overriding image tags for a branch build).
ALL_MODULES = [
    "coding",
    "docker",
    "filesearch",
    "web",
    "archimate",
    "registry",
    "llm",
    "kubernetes",
    "vision",
    "data_access",
    "layout_service",
]

# Namespaces that must never be deployed to or torn down by this service
# (live instances).
_PROTECTED_NAMESPACES = frozenset({"druppie", "druppie-colab-dev"})

# Statuses during which no second deploy/teardown may start.
_TRANSITIONAL_STATUSES = frozenset(
    {"deploying", "deleting"}
)


def _assert_safe_namespace(namespace: str, slug: str) -> None:
    """Refuse any helm/kubectl operation on a live or mismatched namespace.

    Shared by every mutating path (create/redeploy/teardown). A wrong helm
    instance would delete the shared, cluster-scoped
    druppie-kubernetes-readonly ClusterRole and break prod.
    """
    if (
        namespace in _PROTECTED_NAMESPACES
        or not namespace.startswith("druppie-")
        or namespace != f"druppie-{slug}"
    ):
        raise ValidationError(
            f"refusing to operate on protected/mismatched namespace '{namespace}'",
            field="namespace",
        )


def _require_owner_or_admin(env, user_id: UUID, user_roles: list[str], action: str) -> None:
    """Authorize a mutating action on an environment: owner or admin only."""
    if env.owner_id != user_id and "admin" not in user_roles:
        raise AuthorizationError(f"Only owner or admin can {action} a branch environment")

# Subprocess timeouts (seconds).
_KUBECTL_TIMEOUT = 60.0
# Helm --wait can take a while; give it the helm timeout plus a margin.
_HELM_TIMEOUT = 900.0

# Strict image tag validation: a leading alphanumeric then tag-safe chars only.
_IMAGE_TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _slugify(branch: str) -> str:
    """Sanitize a git branch into a DNS-1123 label.

    Lowercase, replace any non-[a-z0-9-] with '-', collapse consecutive dashes,
    strip leading/trailing dashes. Raises ValidationError if the result is empty.
    """
    slug = branch.lower()
    slug = re.sub(r"[^a-z0-9-]", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug)
    slug = slug.strip("-")
    if not slug:
        raise ValidationError(f"branch '{branch}' produced an empty slug", field="branch")
    return slug


def _validate_image_tag(image_tag: str) -> str:
    """Validate an image tag against a strict allowlist regex."""
    if not _IMAGE_TAG_RE.match(image_tag):
        raise ValidationError(f"invalid image tag: {image_tag!r}", field="image_tag")
    return image_tag


class BranchEnvironmentService:
    """Business logic for per-branch Druppie environments."""

    def __init__(self, repo: BranchEnvironmentRepository):
        self.repo = repo

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    async def create(
        self,
        owner_id: UUID,
        branch: str,
        image_tag: str | None,
        user_roles: list[str],
    ) -> BranchEnvironmentDetail:
        """Validate inputs, create the DB record, and kick off the deploy.

        Returns the Detail immediately (status=deploying); the actual helm
        install runs in a tracked background task.
        """
        _ = user_roles  # role gating happens at the route layer
        slug = _slugify(branch)
        namespace = f"druppie-{slug}"
        host = f"druppie-{slug}.{DOMAIN_SUFFIX}"
        url = f"https://{host}"

        # Namespace must be a valid DNS-1123 label (<=63 chars).
        if len(namespace) > 63:
            raise ValidationError(f"namespace '{namespace}' exceeds 63 chars", field="branch")
        # Host must stay a single label under the domain suffix to match the cert.
        if "." in host[: -(len(DOMAIN_SUFFIX) + 1)]:
            raise ValidationError(
                f"host '{host}' is not a single label under {DOMAIN_SUFFIX}", field="branch"
            )

        # SAFETY GUARD: never deploy over the live instances (e.g. branch
        # "colab-dev" would target namespace druppie-colab-dev and overwrite
        # its secrets and helm release).
        _assert_safe_namespace(namespace, slug)

        if image_tag is not None:
            image_tag = _validate_image_tag(image_tag)

        # The unique constraints on branch/slug/namespace decide conflicts
        # atomically (including create races across replicas).
        env = self.repo.create_committed(
            branch=branch,
            slug=slug,
            namespace=namespace,
            url=url,
            owner_id=owner_id,
            image_tag=image_tag,
            status=BranchEnvironmentStatus.DEPLOYING.value,
        )
        if env is None:
            raise ConflictError(f"branch environment already exists for branch '{branch}'")
        env_id = env.id

        logger.info(
            "branch_env_create",
            env_id=str(env_id),
            branch=branch,
            namespace=namespace,
            host=host,
        )

        create_tracked_task(
            self._run_deploy(env_id, slug, namespace, host, image_tag),
            name=f"branch-env-deploy-{env_id}",
        )

        detail = self.repo.get_detail(env_id)
        if detail is None:
            raise NotFoundError("branch_environment", str(env_id))
        return detail

    async def redeploy(
        self,
        env_id: UUID,
        user_id: UUID,
        user_roles: list[str],
        image_tag: str | None = None,
    ) -> BranchEnvironmentDetail:
        """Re-run the helm upgrade for an existing environment (idempotent).

        Owner or admin only. Optionally updates the deployed image tag first.
        """
        # Row lock: serializes the status check-then-flip against concurrent
        # triggers (CI webhook, other replicas) until the commit below.
        env = self.repo.get_by_id(env_id, for_update=True)
        if env is None:
            raise NotFoundError("branch_environment", str(env_id))

        _require_owner_or_admin(env, user_id, user_roles, "redeploy")

        if env.status in _TRANSITIONAL_STATUSES:
            raise ConflictError(
                f"branch environment is already '{env.status}'; wait for it to finish"
            )

        return self._start_redeploy(env, image_tag)

    def _start_redeploy(self, env, image_tag: str | None) -> BranchEnvironmentDetail:
        """Mark the env as deploying and kick off the helm upgrade task.

        Callers must have done authz and status checks.
        """
        if image_tag is not None:
            image_tag = _validate_image_tag(image_tag)
        else:
            image_tag = env.image_tag

        env_id = env.id
        slug = env.slug
        namespace = env.namespace
        host = f"druppie-{slug}.{DOMAIN_SUFFIX}"

        # SAFETY GUARD: re-check in case a stored row is ever inconsistent.
        _assert_safe_namespace(namespace, slug)

        self.repo.update(
            env_id,
            status=BranchEnvironmentStatus.DEPLOYING.value,
            image_tag=image_tag,
            status_message=None,
        )
        self.repo.commit()

        logger.info("branch_env_redeploy", env_id=str(env_id), image_tag=image_tag)

        create_tracked_task(
            self._run_deploy(env_id, slug, namespace, host, image_tag),
            name=f"branch-env-redeploy-{env_id}",
        )

        detail = self.repo.get_detail(env_id)
        if detail is None:
            raise NotFoundError("branch_environment", str(env_id))
        return detail

    async def teardown(
        self,
        env_id: UUID,
        user_id: UUID,
        user_roles: list[str],
    ) -> BranchEnvironmentDetail:
        """Uninstall the environment and delete its namespace + DB row.

        Owner or admin only. Guards against tearing down live/mismatched
        namespaces, and refuses while a deploy is still in flight (a concurrent
        uninstall would race the running helm upgrade and orphan the namespace
        after its DB row is gone).
        """
        env = self.repo.get_by_id(env_id, for_update=True)
        if env is None:
            raise NotFoundError("branch_environment", str(env_id))

        _require_owner_or_admin(env, user_id, user_roles, "tear down")

        if env.status in _TRANSITIONAL_STATUSES:
            raise ConflictError(
                f"branch environment is '{env.status}'; wait for it to finish"
            )

        namespace = env.namespace
        _assert_safe_namespace(namespace, env.slug)

        self.repo.update(
            env_id,
            status=BranchEnvironmentStatus.DELETING.value,
            status_message=None,
        )
        self.repo.commit()

        logger.info("branch_env_teardown", env_id=str(env_id), namespace=namespace)

        create_tracked_task(
            self._run_teardown(env_id, namespace),
            name=f"branch-env-teardown-{env_id}",
        )

        detail = self.repo.get_detail(env_id)
        if detail is None:
            raise NotFoundError("branch_environment", str(env_id))
        return detail

    def list_all(
        self,
        page: int = 1,
        limit: int = 100,
    ):
        """List all branch environments."""
        offset = (page - 1) * limit
        return self.repo.list_all(limit, offset)

    def get(self, env_id: UUID) -> BranchEnvironmentDetail:
        """Get a single branch environment detail."""
        detail = self.repo.get_detail(env_id)
        if detail is None:
            raise NotFoundError("branch_environment", str(env_id))
        return detail

    async def handle_ci_image_push(self, branch: str, image_tag: str) -> bool:
        """Upgrade an existing environment when CI pushes a new branch image.

        Returns True if an environment was found and a redeploy was triggered,
        False if no (non-deleting) environment exists for the branch.
        """
        image_tag = _validate_image_tag(image_tag)
        # Row lock: serializes against a concurrent user redeploy/teardown.
        env = self.repo.get_by_branch(branch, for_update=True)
        if env is None or env.status == BranchEnvironmentStatus.DELETING.value:
            logger.info("branch_env_ci_push_no_env", branch=branch)
            return False
        if env.status == BranchEnvironmentStatus.DEPLOYING.value:
            # A deploy is already in flight; don't race a second helm upgrade.
            logger.info(
                "branch_env_ci_push_skipped_deploying", branch=branch, image_tag=image_tag
            )
            return False
        self._start_redeploy(env, image_tag)
        return True

    # -------------------------------------------------------------------------
    # Background task bodies (fresh DB session each)
    # -------------------------------------------------------------------------

    async def _run_deploy(
        self,
        env_id: UUID,
        slug: str,
        namespace: str,
        host: str,
        image_tag: str | None,
    ) -> None:
        """Provision namespace + secrets, then helm install/upgrade the chart."""
        from ..db.database import SessionLocal

        db = SessionLocal()
        repo = BranchEnvironmentRepository(db)
        try:
            await self._ensure_namespace(namespace)
            await self._copy_secret(
                BRANCH_ENV_TLS_SECRET,
                BRANCH_ENV_TLS_SRC_NS,
                namespace,
                required_keys=("tls.crt", "tls.key"),
            )
            if BRANCH_ENV_PULL_SECRET:
                await self._copy_secret(
                    BRANCH_ENV_PULL_SECRET,
                    BRANCH_ENV_PULL_SECRET_SRC_NS,
                    namespace,
                    required_keys=(".dockerconfigjson",),
                )
            await self._helm_upgrade(namespace, host, image_tag)

            fields = {"status": BranchEnvironmentStatus.RUNNING.value, "status_message": None}
            if image_tag is not None:
                fields["image_tag"] = image_tag
            repo.update(env_id, **fields)
            repo.commit()
            logger.info("branch_env_deploy_succeeded", env_id=str(env_id), namespace=namespace)
        except Exception as e:
            db.rollback()
            message = self._error_message(e)
            repo.update(
                env_id,
                status=BranchEnvironmentStatus.FAILED.value,
                status_message=message,
            )
            repo.commit()
            logger.error(
                "branch_env_deploy_failed",
                env_id=str(env_id),
                namespace=namespace,
                error=str(e),
                exc_info=True,
            )
        finally:
            db.close()

    async def _run_teardown(self, env_id: UUID, namespace: str) -> None:
        """Uninstall the release, delete the namespace, and drop the DB row."""
        from ..db.database import SessionLocal

        db = SessionLocal()
        repo = BranchEnvironmentRepository(db)
        try:
            # helm uninstall (tolerate not-found so teardown is idempotent).
            rc, out, err = await _run_cmd(
                [HELM_PATH, "uninstall", "druppie", "-n", namespace],
                timeout=_HELM_TIMEOUT,
            )
            if rc != 0 and "not found" not in (err + out).lower():
                raise RuntimeError(f"helm uninstall failed: {err.strip() or out.strip()}")

            # Delete the namespace (don't block on finalizers).
            rc, out, err = await _run_cmd(
                [KUBECTL_PATH, "delete", "namespace", namespace, "--wait=false"],
                timeout=_KUBECTL_TIMEOUT,
            )
            if rc != 0 and "not found" not in (err + out).lower():
                raise RuntimeError(f"kubectl delete namespace failed: {err.strip() or out.strip()}")

            repo.delete(env_id)
            repo.commit()
            logger.info("branch_env_teardown_succeeded", env_id=str(env_id), namespace=namespace)
        except Exception as e:
            db.rollback()
            message = self._error_message(e)
            repo.update(
                env_id,
                status=BranchEnvironmentStatus.FAILED.value,
                status_message=message,
            )
            repo.commit()
            logger.error(
                "branch_env_teardown_failed",
                env_id=str(env_id),
                namespace=namespace,
                error=str(e),
                exc_info=True,
            )
        finally:
            db.close()

    # -------------------------------------------------------------------------
    # kubectl / helm helpers
    # -------------------------------------------------------------------------

    async def _ensure_namespace(self, namespace: str) -> None:
        """Create the namespace if it does not already exist."""
        rc, _out, _err = await _run_cmd(
            [KUBECTL_PATH, "get", "namespace", namespace],
            timeout=_KUBECTL_TIMEOUT,
        )
        if rc == 0:
            return
        rc, out, err = await _run_cmd(
            [KUBECTL_PATH, "create", "namespace", namespace],
            timeout=_KUBECTL_TIMEOUT,
        )
        if rc != 0:
            raise RuntimeError(f"failed to create namespace {namespace}: {err.strip() or out.strip()}")

    async def _copy_secret(
        self,
        name: str,
        src_ns: str,
        dst_ns: str,
        required_keys: tuple[str, ...] = (),
    ) -> None:
        """Copy a secret from src_ns into dst_ns (idempotent).

        Reads the secret as JSON, strips all metadata except name, re-targets it
        at the destination namespace, and applies it via ``kubectl apply -f -``
        over stdin (no shell, no temp files). ``required_keys`` must be present
        and non-empty in the source secret's data — copying an empty TLS or
        pull secret would bring the env up broken while it reports RUNNING.
        """
        rc, out, err = await _run_cmd(
            [KUBECTL_PATH, "get", "secret", name, "-n", src_ns, "-o", "json"],
            timeout=_KUBECTL_TIMEOUT,
        )
        if rc != 0:
            raise RuntimeError(
                f"failed to read secret {name} from {src_ns}: {err.strip() or out.strip()}"
            )

        secret = json.loads(out)
        data = secret.get("data") or {}
        for key in required_keys:
            if not data.get(key):
                raise RuntimeError(
                    f"secret {name} in {src_ns} has missing/empty data key '{key}'"
                )
        # Keep only the fields needed to recreate the secret in the new namespace.
        cleaned = {
            "apiVersion": secret.get("apiVersion", "v1"),
            "kind": "Secret",
            "type": secret.get("type", "Opaque"),
            "metadata": {"name": name, "namespace": dst_ns},
            "data": data,
        }
        payload = json.dumps(cleaned).encode("utf-8")

        rc, out, err = await _run_cmd(
            [KUBECTL_PATH, "apply", "-n", dst_ns, "-f", "-"],
            timeout=_KUBECTL_TIMEOUT,
            stdin=payload,
        )
        if rc != 0:
            raise RuntimeError(
                f"failed to apply secret {name} into {dst_ns}: {err.strip() or out.strip()}"
            )

    async def _helm_upgrade(self, namespace: str, host: str, image_tag: str | None) -> None:
        """Run ``helm upgrade --install`` with the branch overrides."""
        chart = BRANCH_ENV_CHART_PATH
        args = [
            HELM_PATH,
            "upgrade",
            "--install",
            "druppie",
            chart,
            "-n",
            namespace,
            "--create-namespace",
            "-f",
            f"{chart}/values.yaml",
            "-f",
            f"{chart}/values-rijnland.yaml",
            "--set",
            f"global.instance={namespace}",
            "--set",
            f"global.domain={host}",
            # Branch envs are reached via Traefik ingress, not NodePort — request
            # ClusterIP so they don't grab cluster-global NodePorts held by the
            # live instance.
            "--set",
            "backend.service.type=ClusterIP",
            "--set",
            "frontend.service.type=ClusterIP",
            "--set",
            "keycloak.service.type=ClusterIP",
            "--set",
            "gitea.service.type=ClusterIP",
            "--set",
            f"backend.nodeSelector.kubernetes\\.io/hostname={BRANCH_ENV_NODE}",
        ]
        for module in PINNED_MODULES:
            args += [
                "--set",
                f"modules.{module}.nodeSelector.kubernetes\\.io/hostname={BRANCH_ENV_NODE}",
            ]
        if BRANCH_ENV_REGISTRY:
            args += ["--set", f"global.imageRegistry={BRANCH_ENV_REGISTRY}"]
        if BRANCH_ENV_PULL_SECRET:
            args += ["--set", f"global.imagePullSecrets[0].name={BRANCH_ENV_PULL_SECRET}"]
        if image_tag is not None:
            args += [
                "--set",
                f"backend.image.tag={image_tag}",
                "--set",
                f"frontend.image.tag={image_tag}",
                "--set",
                f"init.image.tag={image_tag}",
            ]
            for module in ALL_MODULES:
                args += ["--set", f"modules.{module}.image.tag={image_tag}"]
        args += ["--wait", "--timeout", BRANCH_ENV_HELM_TIMEOUT]

        rc, out, err = await _run_cmd(args, timeout=_HELM_TIMEOUT)
        if rc != 0:
            raise RuntimeError(f"helm upgrade failed: {err.strip() or out.strip()}")

    @staticmethod
    def _error_message(exc: Exception) -> str:
        """Trim an error to the last ~900 chars for the status_message column."""
        return str(exc)[-900:]

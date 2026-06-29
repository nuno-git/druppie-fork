"""
K8s Deploy Manager — replaces Docker operations with Kubernetes-native equivalents.

Used by module-docker when DRUPPIE_SANDBOX_MODE=k8s.

Mapping:
  docker build   → Kaniko Job (builds image, pushes to Harbor)
  docker run     → Deployment + Service (with NodePort)
  docker compose → Multiple Deployments + Services from compose YAML
  docker logs    → kubectl logs (pod logs)
  docker stop/rm → Delete Deployment + Service
  docker ps      → List Deployments matching labels
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

import yaml

logger = logging.getLogger(__name__)

DEPLOY_MODE = os.getenv("DRUPPIE_SANDBOX_MODE", "docker")
HARBOR_REGISTRY = os.getenv("HARBOR_REGISTRY", "harbor.rijnland.dev")
HARBOR_PROJECT = os.getenv("HARBOR_PROJECT", "druppie")
K8S_NAMESPACE = os.getenv("DEPLOY_NAMESPACE", "sandbox-runtime")
KANIKO_IMAGE = os.getenv("KANIKO_IMAGE", "gcr.io/kaniko-project/executor:latest")
NODE_PORT_RANGE_START = 30100
NODE_PORT_RANGE_END = 30299

_k8s_client = None
_k8s_apps = None
_k8s_core = None
_k8s_batch = None


def _get_k8s_clients():
    """Lazily initialize Kubernetes API clients."""
    global _k8s_client, _k8s_apps, _k8s_core, _k8s_batch
    if _k8s_client is None:
        from kubernetes import client, config
        try:
            config.load_incluster_config()
        except Exception:
            config.load_kube_config()
        _k8s_client = client.ApiClient()
        _k8s_apps = client.AppsV1Api(_k8s_client)
        _k8s_core = client.CoreV1Api(_k8s_client)
        _k8s_batch = client.BatchV1Api(_k8s_client)
        logger.info("K8s clients initialized (namespace=%s)", K8S_NAMESPACE)
    return _k8s_apps, _k8s_core, _k8s_batch


def _get_free_node_port() -> int:
    """Find a free NodePort in the configured range."""
    apps, core, _ = _get_k8s_clients()
    used = set()
    try:
        services = core.list_namespaced_service(K8S_NAMESPACE)
        for svc in services.items:
            for port in svc.spec.ports or []:
                if port.node_port:
                    used.add(port.node_port)
    except Exception:
        pass
    for port in range(NODE_PORT_RANGE_START, NODE_PORT_RANGE_END + 1):
        if port not in used:
            return port
    raise RuntimeError(f"No free NodePorts in range {NODE_PORT_RANGE_START}-{NODE_PORT_RANGE_END}")


def _labels_for(session_id: str | None, project_id: str | None, user_id: str | None) -> dict:
    labels = {"managed-by": "druppie-module-docker"}
    if session_id:
        labels["druppie.session-id"] = session_id
    if project_id:
        labels["druppie.project-id"] = project_id
    if user_id:
        labels["druppie.user-id"] = user_id
    return labels


async def k8s_build(
    image_name: str,
    git_url: str,
    branch: str = "main",
    dockerfile: str = "Dockerfile",
    build_args: dict[str, str] | None = None,
    session_id: str | None = None,
) -> dict:
    """Build a Docker image using Kaniko (no Docker daemon needed)."""
    _, _, batch = _get_k8s_clients()
    from kubernetes import client

    job_name = f"kaniko-{uuid.uuid4().hex[:8]}"
    destination = f"{HARBOR_REGISTRY}/{HARBOR_PROJECT}/{image_name}"

    args = [
        f"--dockerfile={dockerfile}",
        f"--destination={destination}",
        "--context=dir:///workspace",
        "--cache=true",
    ]
    if build_args:
        for k, v in build_args.items():
            args.append(f"--build-arg={k}={v}")

    init_clone_args = [
        "git", "clone", "--branch", branch, "--depth", "1", git_url, "/workspace"
    ]

    job = client.V1Job(
        metadata=client.V1ObjectMeta(
            name=job_name,
            namespace=K8S_NAMESPACE,
            labels=_labels_for(session_id, None, None),
        ),
        spec=client.V1JobSpec(
            backoff_limit=2,
            ttl_seconds_after_finished=300,
            template=client.V1PodTemplateSpec(
                spec=client.V1PodSpec(
                    restart_policy="Never",
                    init_containers=[
                        client.V1Container(
                            name="clone",
                            image="alpine/git:latest",
                            command=init_clone_args,
                            volume_mounts=[
                                client.V1VolumeMount(name="workspace", mount_path="/workspace")
                            ],
                        )
                    ],
                    containers=[
                        client.V1Container(
                            name="kaniko",
                            image=KANIKO_IMAGE,
                            args=args,
                            volume_mounts=[
                                client.V1VolumeMount(name="workspace", mount_path="/workspace")
                            ],
                        )
                    ],
                    volumes=[
                        client.V1Volume(
                            name="workspace",
                            empty_dir=client.V1EmptyDirVolumeSource(),
                        )
                    ],
                )
            ),
        ),
    )

    batch.create_namespaced_job(K8S_NAMESPACE, job)
    logger.info("Kaniko job created: %s (image=%s)", job_name, destination)

    return {
        "success": True,
        "image_name": destination,
        "job_name": job_name,
        "message": f"Build job '{job_name}' submitted. Image will be at {destination}",
    }


async def k8s_run(
    image_name: str,
    container_name: str,
    container_port: int,
    project_id: str | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
    env_vars: dict[str, str] | None = None,
    command: str | None = None,
) -> dict:
    """Run a container as a Kubernetes Deployment + Service."""
    from kubernetes import client
    apps, core, _ = _get_k8s_clients()

    labels = _labels_for(session_id, project_id, user_id)
    labels["app"] = container_name

    node_port = _get_free_node_port()

    env_list = None
    if env_vars:
        env_list = [
            client.V1EnvVar(name=k, value=str(v))
            for k, v in env_vars.items()
        ]

    container_args = command.split() if command else None

    deployment = client.V1Deployment(
        metadata=client.V1ObjectMeta(
            name=container_name,
            namespace=K8S_NAMESPACE,
            labels=labels,
        ),
        spec=client.V1DeploymentSpec(
            replicas=1,
            selector=client.V1LabelSelector(match_labels={"app": container_name}),
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels=labels),
                spec=client.V1PodSpec(
                    containers=[
                        client.V1Container(
                            name="app",
                            image=image_name,
                            ports=[client.V1ContainerPort(container_port=container_port)],
                            env=env_list,
                            args=container_args,
                        )
                    ]
                ),
            ),
        ),
    )

    service = client.V1Service(
        metadata=client.V1ObjectMeta(
            name=f"{container_name}-svc",
            namespace=K8S_NAMESPACE,
            labels=labels,
        ),
        spec=client.V1ServiceSpec(
            type="NodePort",
            selector={"app": container_name},
            ports=[
                client.V1ServicePort(
                    port=container_port,
                    target_port=container_port,
                    node_port=node_port,
                )
            ],
        ),
    )

    try:
        apps.create_namespaced_deployment(K8S_NAMESPACE, deployment)
    except Exception as e:
        if "already exists" in str(e):
            apps.patch_namespaced_deployment(container_name, K8S_NAMESPACE, deployment)
        else:
            raise

    try:
        core.create_namespaced_service(K8S_NAMESPACE, service)
    except Exception as e:
        if "already exists" not in str(e):
            logger.warning("Failed to create service: %s", e)

    logger.info("K8s deployment created: %s (port=%d)", container_name, node_port)

    return {
        "success": True,
        "container_name": container_name,
        "port": node_port,
        "url": f"http://localhost:{node_port}",
        "labels": labels,
    }


async def k8s_compose_up(
    compose_yaml: str,
    project_name: str,
    session_id: str | None = None,
    project_id: str | None = None,
    health_path: str = "/health",
    health_timeout: int = 300,
) -> dict:
    """Translate docker-compose YAML to K8s resources and apply them."""
    from kubernetes import client
    apps, core, _ = _get_k8s_clients()

    compose = yaml.safe_load(compose_yaml)
    services = compose.get("services", {})
    if not services:
        return {"success": False, "error": "No services found in compose file"}

    labels = _labels_for(session_id, project_id, None)
    labels["compose-project"] = project_name
    created_resources = []
    main_port = None

    for svc_name, svc_config in services.items():
        full_name = f"{project_name}-{svc_name}"
        image = svc_config.get("image", f"{project_name}-{svc_name}:latest")
        ports = svc_config.get("ports", [])
        env_list = []
        for k, v in (svc_config.get("environment") or {}).items():
            env_list.append(client.V1EnvVar(name=k, value=str(v)))

        container_ports = []
        target_port = 80
        for p in ports:
            if isinstance(p, str) and ":" in p:
                host_p, container_p = p.split(":")
                target_port = int(container_p)
            elif isinstance(p, int):
                target_port = p
            elif isinstance(p, dict):
                target_port = p.get("target", 80)
            container_ports.append(client.V1ContainerPort(container_port=target_port))

        svc_labels = {**labels, "app": full_name}
        node_port = _get_free_node_port() if svc_name == "app" else None

        readiness_probe = None
        if svc_name == "app" and health_path:
            readiness_probe = client.V1Probe(
                http_get=client.V1HTTPGetAction(path=health_path, port=target_port),
                initial_delay_seconds=5,
                period_seconds=10,
            )

        deployment = client.V1Deployment(
            metadata=client.V1ObjectMeta(name=full_name, namespace=K8S_NAMESPACE, labels=svc_labels),
            spec=client.V1DeploymentSpec(
                replicas=1,
                selector=client.V1LabelSelector(match_labels={"app": full_name}),
                template=client.V1PodTemplateSpec(
                    metadata=client.V1ObjectMeta(labels=svc_labels),
                    spec=client.V1PodSpec(
                        containers=[
                            client.V1Container(
                                name=svc_name,
                                image=image,
                                ports=container_ports or None,
                                env=env_list or None,
                                readiness_probe=readiness_probe,
                            )
                        ]
                    ),
                ),
            ),
        )

        svc_spec_ports = [
            client.V1ServicePort(port=target_port, target_port=target_port)
        ]
        svc_type = "ClusterIP"
        if node_port:
            svc_spec_ports[0].node_port = node_port
            svc_type = "NodePort"
            main_port = node_port

        service = client.V1Service(
            metadata=client.V1ObjectMeta(name=f"{full_name}-svc", namespace=K8S_NAMESPACE, labels=svc_labels),
            spec=client.V1ServiceSpec(
                type=svc_type,
                selector={"app": full_name},
                ports=svc_spec_ports,
            ),
        )

        try:
            apps.create_namespaced_deployment(K8S_NAMESPACE, deployment)
        except Exception as e:
            if "already exists" in str(e):
                apps.patch_namespaced_deployment(full_name, K8S_NAMESPACE, deployment)
            else:
                logger.warning("Failed to create deployment %s: %s", full_name, e)

        try:
            core.create_namespaced_service(K8S_NAMESPACE, service)
        except Exception as e:
            if "already exists" not in str(e):
                logger.warning("Failed to create service %s: %s", full_name, e)

        created_resources.append(full_name)

    logger.info("Compose deployed: %s (%d services, port=%s)",
                project_name, len(created_resources), main_port)

    return {
        "success": True,
        "url": f"http://localhost:{main_port}" if main_port else None,
        "port": main_port,
        "compose_project_name": project_name,
        "containers": created_resources,
        "health_check": "submitted",
        "labels": labels,
    }


async def k8s_compose_down(project_name: str) -> dict:
    """Delete all K8s resources for a compose project."""
    from kubernetes import client
    apps, core, _ = _get_k8s_clients()

    label_selector = f"compose-project={project_name}"
    deleted = []

    try:
        deps = apps.list_namespaced_deployment(K8S_NAMESPACE, label_selector=label_selector)
        for dep in deps.items:
            apps.delete_namespaced_deployment(dep.metadata.name, K8S_NAMESPACE)
            deleted.append(dep.metadata.name)
    except Exception:
        pass

    try:
        svcs = core.list_namespaced_service(K8S_NAMESPACE, label_selector=label_selector)
        for svc in svcs.items:
            core.delete_namespaced_service(svc.metadata.name, K8S_NAMESPACE)
    except Exception:
        pass

    logger.info("Compose deleted: %s (%d deployments)", project_name, len(deleted))
    return {"success": True, "removed": deleted}


async def k8s_stop(container_name: str) -> dict:
    """Scale a deployment to 0."""
    from kubernetes import client
    apps, _, _ = _get_k8s_clients()

    try:
        body = {"spec": {"replicas": 0}}
        apps.patch_namespaced_deployment_scale(container_name, K8S_NAMESPACE, body)
        return {"success": True, "container_name": container_name, "status": "stopped"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def k8s_remove(container_name: str) -> dict:
    """Delete a deployment and its service."""
    from kubernetes import client
    apps, core, _ = _get_k8s_clients()

    try:
        apps.delete_namespaced_deployment(container_name, K8S_NAMESPACE)
    except Exception:
        pass
    try:
        core.delete_namespaced_service(f"{container_name}-svc", K8S_NAMESPACE)
    except Exception:
        pass

    return {"success": True, "container_name": container_name, "status": "removed"}


async def k8s_logs(container_name: str, tail: int = 100) -> dict:
    """Get logs from the first pod of a deployment."""
    core = _get_k8s_clients()[1]

    try:
        pods = core.list_namespaced_pod(
            K8S_NAMESPACE, label_selector=f"app={container_name}"
        )
        if not pods.items:
            return {"success": False, "error": "No pods found"}
        pod_name = pods.items[0].metadata.name
        logs = core.read_namespaced_pod_log(pod_name, K8S_NAMESPACE, tail_lines=tail)
        return {"success": True, "container_name": container_name, "logs": logs}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def k8s_list_containers(
    session_id: str | None = None,
    project_id: str | None = None,
) -> list[dict]:
    """List deployments managed by module-docker."""
    apps = _get_k8s_clients()[0]

    selector = "managed-by=druppie-module-docker"
    if session_id:
        selector += f",druppie.session-id={session_id}"
    if project_id:
        selector += f",druppie.project-id={project_id}"

    try:
        deps = apps.list_namespaced_deployment(K8S_NAMESPACE, label_selector=selector)
        result = []
        for dep in deps.items:
            result.append({
                "name": dep.metadata.name,
                "replicas": dep.spec.replicas,
                "ready": dep.status.ready_replicas or 0,
                "labels": dep.metadata.labels or {},
            })
        return result
    except Exception as e:
        logger.warning("Failed to list deployments: %s", e)
        return []

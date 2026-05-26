"""Integration tests for Sysbox sandbox containers.

Creates real Docker containers using the sysbox-runc runtime and verifies:
- Docker CLI availability inside the nested container
- Non-root user is active
- Cache volume is mounted and writable
- Security flags are correctly applied
- Runtime is sysbox-runc

Tests are SKIPPED if sysbox-runc runtime or druppie-sandbox:latest image
is not available on the host Docker daemon.
"""

import subprocess
import time

import pytest


def _run(cmd, **kwargs):
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def _sysbox_available():
    try:
        result = _run(["docker", "info", "--format", "{{.Runtimes}}"])
        return "sysbox-runc" in result.stdout
    except FileNotFoundError:
        return False


def _image_available():
    try:
        result = _run(["docker", "image", "inspect", "druppie-sandbox:latest"])
        return result.returncode == 0
    except FileNotFoundError:
        return False


def _docker_accessible():
    try:
        result = _run(["docker", "info"])
        return result.returncode == 0
    except FileNotFoundError:
        return False


skip_no_sysbox = pytest.mark.skipif(
    not _sysbox_available() or not _image_available(),
    reason="sysbox-runc runtime or druppie-sandbox:latest image not available",
)

skip_no_docker = pytest.mark.skipif(
    not _docker_accessible(),
    reason="Docker daemon not accessible",
)

CONTAINER_PREFIX = "test-sandbox-integration-"


@pytest.fixture(autouse=True)
def cleanup_containers():
    yield
    result = _run(
        [
            "docker",
            "ps",
            "-a",
            "--filter",
            f"name={CONTAINER_PREFIX}",
            "--format",
            "{{.Names}}",
        ]
    )
    for name in result.stdout.strip().split("\n"):
        if name:
            _run(["docker", "rm", "-f", name])


def _create_test_container(name, extra_args=None):
    cmd = [
        "docker",
        "run",
        "-d",
        "--name",
        name,
        "--runtime",
        "sysbox-runc",
        "--security-opt",
        "no-new-privileges",
        "--cap-drop",
        "ALL",
        "--cap-add",
        "NET_RAW",
        "--memory",
        "4g",
        "--pids-limit",
        "8192",
        "--cpus",
        "2",
        "--tmpfs",
        "/tmp:size=512m",
        "-w",
        "/workspace",
        "-v",
        "sandbox_dep_cache:/cache",
        "druppie-sandbox:latest",
        "bash", "-c", "dockerd >/dev/null 2>&1 & sleep infinity",
    ]
    if extra_args:
        cmd = extra_args + cmd
    result = _run(cmd)
    assert result.returncode == 0, f"docker run failed: {result.stderr}"
    return name


def _exec_in_container(name, command):
    result = _run(["docker", "exec", name, "bash", "-c", command])
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _wait_for_docker(name, timeout=60):
    start = time.time()
    while time.time() - start < timeout:
        rc, out, err = _exec_in_container(name, "docker info >/dev/null 2>&1 && echo ready")
        if "ready" in out:
            return True
        time.sleep(2)
    return False


def _container_name(test_id):
    return f"{CONTAINER_PREFIX}{test_id}"


@skip_no_docker
@skip_no_sysbox
def test_docker_cli_available():
    name = _container_name("docker-cli")
    _create_test_container(name)

    assert _wait_for_docker(name), "Nested Docker daemon did not become ready in time"

    rc, out, err = _exec_in_container(name, "docker --version")
    assert rc == 0, f"docker --version failed: {err}"
    assert "command not found" not in err, "docker CLI not found in container"

    rc, out, err = _exec_in_container(name, "docker ps")
    assert rc == 0, f"docker ps failed: stdout={out} stderr={err}"


@skip_no_docker
@skip_no_sysbox
def test_root_user():
    name = _container_name("root-user")
    _create_test_container(name)

    rc, out, err = _exec_in_container(name, "whoami")
    assert rc == 0, f"whoami failed: {err}"
    assert out == "root", f"Expected user 'root' (Sysbox maps safely), got '{out}'"


@skip_no_docker
@skip_no_sysbox
def test_cache_volume_mounted():
    name = _container_name("cache-volume")
    _create_test_container(name)

    rc, out, err = _exec_in_container(name, "test -d /cache && echo exists")
    assert rc == 0, f"/cache directory check failed: {err}"
    assert "exists" in out, "/cache directory does not exist"

    rc, out, err = _exec_in_container(name, "touch /cache/.write_test && echo writable")
    assert rc == 0, f"/cache write test failed: {err}"
    assert "writable" in out, "/cache is not writable"


@skip_no_docker
@skip_no_sysbox
def test_security_flags():
    name = _container_name("security-flags")
    _create_test_container(name)

    result = _run(["docker", "inspect", "--format", "{{json .HostConfig}}", name])
    assert result.returncode == 0, f"docker inspect failed: {result.stderr}"

    import json

    host_config = json.loads(result.stdout)
    assert host_config, "docker inspect returned empty HostConfig"

    security_opt = host_config.get("SecurityOpt", [])
    assert "no-new-privileges" in security_opt, (
        f"SecurityOpt should contain 'no-new-privileges', got: {security_opt}"
    )

    cap_drop = host_config.get("CapDrop", [])
    assert "ALL" in cap_drop, f"CapDrop should contain 'ALL', got: {cap_drop}"

    memory = host_config.get("Memory", 0)
    assert memory > 0, f"Memory limit should be set, got: {memory}"

    pids_limit = host_config.get("PidsLimit", 0)
    assert pids_limit > 0, f"PidsLimit should be set, got: {pids_limit}"

    nano_cpus = host_config.get("NanoCpus", 0)
    assert nano_cpus != 0, f"NanoCpus should be set, got: {nano_cpus}"

    privileged = host_config.get("Privileged", False)
    assert not privileged, "Container should NOT be privileged"


@skip_no_docker
@skip_no_sysbox
def test_runtime_is_sysbox():
    name = _container_name("runtime")
    _create_test_container(name)

    result = _run(["docker", "inspect", "--format", "{{.HostConfig.Runtime}}", name])
    assert result.returncode == 0, f"docker inspect failed: {result.stderr}"
    runtime = result.stdout.strip()
    assert runtime == "sysbox-runc", f"Expected runtime 'sysbox-runc', got '{runtime}'"

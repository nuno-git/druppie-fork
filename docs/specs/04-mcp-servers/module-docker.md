# module-docker

**Port:** 9002. **Type:** core. **Dockerfile:** `druppie/mcp-servers/module-docker/Dockerfile`.

Runs deployments for projects built by the `deployer` agent. 10 tools. Holds an allocatable port pool and enforces ownership via Docker labels.

## Dockerfile

- Base: `python:3.11-slim`.
- Installs Docker CLI from `get.docker.com` install script.
- Expects `/var/run/docker.sock` mounted from host.
- Env: `DOCKER_NETWORK=druppie-new-network`, `MCP_PORT=9002`.

## `requirements.txt`

- `fastmcp>=2.0.0,<3.0.0`
- `pyyaml>=6.0`
- `uvicorn>=0.24.0`

## Port pool

`PORT_RANGE_START=9100`, `PORT_RANGE_END=9199`. Allocated per container.

Data structures (`v1/tools.py`):
- `used_ports: set[int]` — in-process tracker.
- `_port_lock: asyncio.Lock` — prevents TOCTOU races.
- `compose_port_registry: dict[str, int]` — maps compose project name → its allocated port (for teardown).

Allocation flow (`get_next_port()`):
1. Acquire lock.
2. Query `docker ps --format '{{.Ports}}'` to discover externally-bound ports.
3. Find first port in [9100, 9199] not in `docker ps` result AND not in `used_ports`.
4. Reserve it, release lock.

If the pool is exhausted, an exception is raised — the tool call fails with a clear message.

## Container labels

Every container started by `run` or `compose_up` is labeled:
- `druppie.project_id=<uuid>`
- `druppie.session_id=<uuid>`
- `druppie.user_id=<uuid>`
- `druppie.git_url=<url>`
- `druppie.branch=<name>`

The `/api/deployments` route inspects these labels to scope containers to users and projects. `list_containers` tool can filter by any of them.

## Tools (10)

### `build`

Clones a Gitea repo to a temporary directory, runs `docker build`, then deletes the clone.

Args: `image_name`, `git_url?` or `(repo_name, repo_owner)`, `branch?`, `project_id`, `session_id`, `dockerfile?`, `build_args?`.

Returns: `{success, image_name, build_log, project_id, session_id}`.

### `run`

Starts a container from an image, attaches to the main Docker network, allocates a port if needed.

Args: `image_name`, `container_name`, `container_port?`, `project_id`, `session_id`, `user_id`, `git_url?`, `branch?`, `port?`, `port_mapping?`, `env_vars?`, `volumes?`, `command?`.

Returns: `{success, container_name, container_id, port, url, labels}`.

### `compose_up`

The main deployment tool. Clones a repo, verifies `docker-compose.yaml` is present, allocates a host port, writes a compose override to add labels, then runs `docker compose up -d --build`. Performs a health check against `{project_name}-app-1:{container_port}{health_path}` over the internal Docker network.

Args: `repo_name?` or `git_url?`, `branch?`, `compose_project_name`, `project_id`, `session_id`, `user_id`, `health_path?` (default `/health`), `health_timeout?`.

Flow:
1. Clone to `/tmp/docker-builds/<uuid>`.
2. Discover container port from compose file.
3. Allocate host port.
4. Write override with labels + port mapping.
5. `docker compose -p <project_name> up -d --build`.
6. HTTP-check health endpoint on internal network, retrying up to `health_timeout`.
7. Return `{success, url, port, compose_project_name, containers, health_check, labels}`.

Cleanup guarantee: the clone directory is removed in a `finally` block even on failure.

### `compose_down`

Stops and removes a compose project.

Args: `compose_project_name`, `remove_volumes?`.

Port reclamation: checks the in-process registry first, falls back to `docker compose ps` to discover bound ports, then releases them.

### `stop` / `remove`

Stop a container (optionally remove), or hard-remove a container.

### `logs`

Return container logs with `tail` lines (default 100). `follow` is not supported in the MCP call (not streaming).

### `list_containers`

Optional filters: `all?`, `project_id?`, `session_id?`, `user_id?` (matched against labels).

Returns `{success, containers: [...], count}`.

### `inspect`

Returns `{success, id, name, image, status, created, ports, labels}` — only `druppie.*` labels are included.

### `exec_command`

`docker exec` in a running container. Args: `container_name`, `command`, `workdir?`.

Returns `{success, stdout, stderr, return_code}`. Used by deployer for post-deploy smoke tests.

## Deployer agent flow

The `deployer` agent uses this module as follows (see `druppie/agents/definitions/deployer.yaml`):

1. `docker_list_containers(project_id=…)` — discover existing.
2. `docker_compose_up(repo_name=…, branch=…, compose_project_name=…, …)` — **requires developer approval**.
3. Health check runs inline (inside `compose_up`) against `/health`.
4. `hitl_ask_question` — ask user if deployment looks good.
5. Call `done()` with the feedback.

For update projects:
- Preview deploy: `compose_project_name = "<project>-preview"`.
- Final deploy: stops preview + old production + deploys new `<project>`.

## Networking

Containers join `druppie-new-network`. Health checks from `compose_up` use the internal Docker network (`http://<project>-app-1:<container_port>/health`), not the external port, to avoid NAT issues.

## Security

- All mutating operations require `developer` role approval (global default in `mcp_config.yaml`).
- Command injection on `exec_command` is limited by the MCP tool definition only accepting a string — but the docker daemon runs it in the container's default shell. Don't expose this module to untrusted agents.
- The Docker socket mount grants root-equivalent on the host. Dedicated deploy hosts are expected.

"""
Sandbox exec daemon.

Exposes a narrow HTTP API on a unix socket. The host-side pi orchestrator drives
all tool operations through this daemon — bash, file reads/writes/edits,
listings, greps, finds, and a final `git bundle` handoff.

The sandbox contains no LLM credentials, no git push credentials, and no
host filesystem access. The workspace at /workspace is VM-local; the only
shared path is /out, where bundles and logs are written for the host to read.

Auth: the daemon reads SANDBOX_AUTH_TOKEN from env at startup. Every request
must include it in the Authorization header. A missing/mismatched token
returns 401.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import sys
from pathlib import Path
from typing import Any

from aiohttp import web

WORKSPACE = Path(os.environ.get("SANDBOX_WORKSPACE", "/workspace"))
OUT_DIR = Path(os.environ.get("SANDBOX_OUT_DIR", "/out"))
# Default to TCP on 0.0.0.0:8000 — the host maps this to loopback with a random
# published port. A unix socket is still supported when SANDBOX_SOCKET is set.
SOCKET_PATH = os.environ.get("SANDBOX_SOCKET", "")
BIND_HOST = os.environ.get("SANDBOX_BIND_HOST", "0.0.0.0")
BIND_PORT = int(os.environ.get("SANDBOX_BIND_PORT", "8000"))
AUTH_TOKEN = os.environ.get("SANDBOX_AUTH_TOKEN", "")

# Keep a bounded set of in-flight exec tasks so the daemon exits cleanly on shutdown
_inflight: set[asyncio.Task[Any]] = set()


def _abs_in_workspace(rel: str) -> Path:
    """Resolve a path relative to /workspace, rejecting escapes via .. or absolute paths."""
    p = (WORKSPACE / rel).resolve()
    try:
        p.relative_to(WORKSPACE.resolve())
    except ValueError:
        raise web.HTTPBadRequest(reason=f"path escapes workspace: {rel}")
    return p


@web.middleware
async def auth_middleware(request: web.Request, handler):  # type: ignore[no-untyped-def]
    # Health check is unauthenticated (no sensitive info leaked)
    if request.path == "/health":
        return await handler(request)
    if not AUTH_TOKEN:
        return web.json_response({"error": "daemon has no auth token configured"}, status=503)
    header = request.headers.get("Authorization", "")
    expected = f"Bearer {AUTH_TOKEN}"
    if header != expected:
        return web.json_response({"error": "unauthorized"}, status=401)
    return await handler(request)


# ── Endpoints ──────────────────────────────────────────────────────────────


async def health(_request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "workspace": str(WORKSPACE)})


async def exec_cmd(request: web.Request) -> web.StreamResponse:
    """Run a bash command. Streams stdout+stderr as SSE frames and a final exit event."""
    body = await request.json()
    command: str = body["command"]
    cwd_rel: str = body.get("cwd") or ""
    timeout: float | None = body.get("timeout")

    cwd = _abs_in_workspace(cwd_rel) if cwd_rel else WORKSPACE

    resp = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
    await resp.prepare(request)

    proc = await asyncio.create_subprocess_exec(
        "/bin/bash", "-c", command,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "HOME": os.environ.get("HOME", "/home/sandbox")},
    )

    timed_out = False

    async def pump(stream: asyncio.StreamReader | None, kind: str) -> None:
        if stream is None:
            return
        while True:
            chunk = await stream.read(8192)
            if not chunk:
                return
            frame = json.dumps({"stream": kind, "data": chunk.decode("utf-8", errors="replace")})
            await resp.write(f"event: data\ndata: {frame}\n\n".encode("utf-8"))

    async def watchdog() -> None:
        nonlocal timed_out
        if timeout is None or timeout <= 0:
            return
        await asyncio.sleep(timeout)
        if proc.returncode is None:
            timed_out = True
            with contextlib_suppress(ProcessLookupError):
                proc.kill()

    wd = asyncio.create_task(watchdog())
    _inflight.add(wd)
    try:
        await asyncio.gather(pump(proc.stdout, "stdout"), pump(proc.stderr, "stderr"))
        exit_code = await proc.wait()
    finally:
        _inflight.discard(wd)
        wd.cancel()

    payload = {"exitCode": exit_code, "timedOut": timed_out}
    await resp.write(f"event: exit\ndata: {json.dumps(payload)}\n\n".encode("utf-8"))
    await resp.write_eof()
    return resp


async def read_file(request: web.Request) -> web.Response:
    body = await request.json()
    path = _abs_in_workspace(body["path"])
    if not path.exists():
        return web.json_response({"error": "not found"}, status=404)
    data = path.read_bytes()
    # Try utf-8; if binary, return base64
    try:
        return web.json_response({"content": data.decode("utf-8"), "encoding": "utf-8", "size": len(data)})
    except UnicodeDecodeError:
        import base64
        return web.json_response({"content": base64.b64encode(data).decode("ascii"), "encoding": "base64", "size": len(data)})


async def write_file(request: web.Request) -> web.Response:
    body = await request.json()
    path = _abs_in_workspace(body["path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    content = body["content"]
    encoding = body.get("encoding", "utf-8")
    if encoding == "base64":
        import base64
        path.write_bytes(base64.b64decode(content))
    else:
        path.write_text(content, encoding="utf-8")
    return web.json_response({"ok": True, "size": path.stat().st_size})


async def access(request: web.Request) -> web.Response:
    body = await request.json()
    path = _abs_in_workspace(body["path"])
    mode = body.get("mode", "r")  # "r" or "rw"
    if not path.exists():
        return web.json_response({"ok": False, "error": "not found"}, status=404)
    import os as _os
    check = _os.R_OK
    if mode == "rw":
        check |= _os.W_OK
    if not _os.access(str(path), check):
        return web.json_response({"ok": False, "error": "permission denied"}, status=403)
    return web.json_response({"ok": True})


async def stat(request: web.Request) -> web.Response:
    body = await request.json()
    path = _abs_in_workspace(body["path"])
    if not path.exists():
        return web.json_response({"exists": False})
    st = path.stat()
    return web.json_response({
        "exists": True,
        "isFile": path.is_file(),
        "isDirectory": path.is_dir(),
        "size": st.st_size,
        "mtimeMs": int(st.st_mtime * 1000),
    })


async def listdir(request: web.Request) -> web.Response:
    body = await request.json()
    path = _abs_in_workspace(body["path"] or "")
    if not path.exists():
        return web.json_response({"error": "not found"}, status=404)
    if not path.is_dir():
        return web.json_response({"error": "not a directory"}, status=400)
    entries = []
    for entry in sorted(path.iterdir(), key=lambda e: e.name):
        st = entry.stat()
        entries.append({
            "name": entry.name,
            "isFile": entry.is_file(),
            "isDirectory": entry.is_dir(),
            "size": st.st_size,
        })
    return web.json_response({"entries": entries})


async def find(request: web.Request) -> web.Response:
    """Glob via `fd` — no Python glob so patterns match what humans expect."""
    body = await request.json()
    pattern: str = body["pattern"]
    search_rel: str = body.get("path") or ""
    limit: int = int(body.get("limit", 1000))
    search = _abs_in_workspace(search_rel) if search_rel else WORKSPACE
    if not search.exists():
        return web.json_response({"error": "not found"}, status=404)

    # Use fd for fast, gitignore-respecting glob; exclude node_modules/.git by default
    proc = await asyncio.create_subprocess_exec(
        "fd", "--glob", pattern, "--type", "f",
        "--exclude", "node_modules", "--exclude", ".git",
        "--absolute-path",
        str(search),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    files = stdout.decode("utf-8", errors="replace").splitlines()
    return web.json_response({"files": files[:limit]})


async def grep(request: web.Request) -> web.Response:
    """Grep via ripgrep."""
    body = await request.json()
    pattern: str = body["pattern"]
    search_rel: str = body.get("path") or ""
    glob: str | None = body.get("glob")
    limit: int = int(body.get("limit", 100))
    search = _abs_in_workspace(search_rel) if search_rel else WORKSPACE

    args = ["rg", "--json", "--max-count", "1000", pattern, str(search)]
    if glob:
        args.insert(2, "--glob")
        args.insert(3, glob)

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    matches: list[dict[str, Any]] = []
    for line in stdout.decode("utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("type") == "match":
            d = msg["data"]
            matches.append({
                "file": d["path"]["text"],
                "line": d["line_number"],
                "text": d["lines"]["text"].rstrip("\n"),
            })
            if len(matches) >= limit:
                break
    return web.json_response({"matches": matches})


async def import_bundle(request: web.Request) -> web.Response:
    """
    Import a git bundle (produced with `git bundle create --all`) as the
    starting state of /workspace. Every branch in the bundle becomes a local
    branch. We then check out the branch named by ?branch=...
    """
    branch = request.query.get("branch")
    if not branch:
        return web.json_response({"ok": False, "error": "branch query param is required"}, status=400)

    tmp_path = "/tmp/import.bundle"
    data = await request.read()
    with open(tmp_path, "wb") as f:
        f.write(data)

    WORKSPACE.mkdir(parents=True, exist_ok=True)
    if not (WORKSPACE / ".git").exists():
        rc, _, stderr = await _run_sub("git", "init", str(WORKSPACE))
        if rc != 0:
            return web.json_response({"ok": False, "error": f"git init: {stderr}"}, status=500)

    # Bring in every ref from the bundle as a local branch.
    rc, _, stderr = await _run_sub(
        "git", "-C", str(WORKSPACE), "fetch", tmp_path, "+refs/heads/*:refs/heads/*",
    )
    if rc != 0:
        return web.json_response({"ok": False, "error": f"git fetch bundle: {stderr}"}, status=500)

    # Check out the requested starting branch.
    rc, _, stderr = await _run_sub("git", "-C", str(WORKSPACE), "checkout", branch)
    if rc != 0:
        return web.json_response({"ok": False, "error": f"git checkout {branch}: {stderr}"}, status=500)

    # Clean any stray state.
    await _run_sub("git", "-C", str(WORKSPACE), "reset", "--hard", branch)

    try:
        os.remove(tmp_path)
    except OSError:
        pass

    return web.json_response({"ok": True, "branch": branch})


async def _run_sub(*args: str) -> tuple[int, str, str]:
    p = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await p.communicate()
    return (p.returncode or 0, stdout.decode(errors="replace"), stderr.decode(errors="replace"))


async def git_bundle(request: web.Request) -> web.Response:
    """Create a git bundle of all refs at /out/run.bundle."""
    body = await request.json()
    refs: list[str] = body.get("refs") or ["--all"]
    name = body.get("name", "run.bundle")
    out_path = OUT_DIR / name
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    proc = await asyncio.create_subprocess_exec(
        "git", "-C", str(WORKSPACE), "bundle", "create", str(out_path), *refs,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        return web.json_response({
            "ok": False,
            "error": stderr.decode("utf-8", errors="replace"),
        }, status=500)
    return web.json_response({
        "ok": True,
        "bundlePath": str(out_path),
        "size": out_path.stat().st_size,
    })


async def init_workspace(request: web.Request) -> web.Response:
    """Initialise the workspace: git init + user config + optional branch + optional remote URL in .git/config."""
    body = await request.json()
    user_name = body.get("userName", "oneshot-tdd-agent")
    user_email = body.get("userEmail", "agent@oneshot-tdd.local")
    branch = body.get("branch", "main")
    remote_url = body.get("remoteUrl")

    WORKSPACE.mkdir(parents=True, exist_ok=True)
    git_dir = WORKSPACE / ".git"
    if not git_dir.exists():
        await (await asyncio.create_subprocess_exec("git", "init", "-b", branch, str(WORKSPACE))).wait()
    await (await asyncio.create_subprocess_exec("git", "-C", str(WORKSPACE), "config", "user.name", user_name)).wait()
    await (await asyncio.create_subprocess_exec("git", "-C", str(WORKSPACE), "config", "user.email", user_email)).wait()
    if remote_url:
        # Stored in .git/config but never used inside the sandbox (no creds).
        # The host-side push reads this to know where to push.
        await (await asyncio.create_subprocess_exec(
            "git", "-C", str(WORKSPACE), "config", "--unset-all", "remote.origin.url"
        )).wait()
        await (await asyncio.create_subprocess_exec(
            "git", "-C", str(WORKSPACE), "remote", "add", "origin", remote_url
        )).wait()
    # Make sure there's at least one commit so branches can be created
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", str(WORKSPACE), "rev-parse", "HEAD",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    await proc.wait()
    if proc.returncode != 0:
        await (await asyncio.create_subprocess_exec(
            "git", "-C", str(WORKSPACE), "commit", "--allow-empty", "-m", "initial commit",
        )).wait()
    return web.json_response({"ok": True, "workspace": str(WORKSPACE)})


# ── Helpers ────────────────────────────────────────────────────────────────


class contextlib_suppress:
    """Tiny context manager to replace contextlib.suppress — avoids the import."""
    def __init__(self, *excs: type[BaseException]) -> None:
        self.excs = excs
    def __enter__(self) -> None:
        return None
    def __exit__(self, exc_type, exc, tb) -> bool:  # type: ignore[no-untyped-def]
        return exc_type is not None and issubclass(exc_type, self.excs)


def build_app() -> web.Application:
    app = web.Application(middlewares=[auth_middleware], client_max_size=512 * 1024 * 1024)
    app.router.add_get("/health", health)
    app.router.add_post("/exec", exec_cmd)
    app.router.add_post("/read", read_file)
    app.router.add_post("/write", write_file)
    app.router.add_post("/access", access)
    app.router.add_post("/stat", stat)
    app.router.add_post("/ls", listdir)
    app.router.add_post("/find", find)
    app.router.add_post("/grep", grep)
    app.router.add_post("/bundle", git_bundle)
    app.router.add_post("/import-bundle", import_bundle)
    app.router.add_post("/init", init_workspace)
    return app


async def _amain() -> None:
    app = build_app()
    runner = web.AppRunner(app)
    await runner.setup()

    sites: list[web.BaseSite] = []
    if SOCKET_PATH:
        sock_dir = Path(SOCKET_PATH).parent
        sock_dir.mkdir(parents=True, exist_ok=True)
        if Path(SOCKET_PATH).exists():
            Path(SOCKET_PATH).unlink()
        sites.append(web.UnixSite(runner, SOCKET_PATH))
    if BIND_HOST:
        sites.append(web.TCPSite(runner, BIND_HOST, BIND_PORT))
    for s in sites:
        await s.start()
    if SOCKET_PATH:
        try:
            os.chmod(SOCKET_PATH, 0o660)
        except OSError:
            pass

    listeners = []
    if SOCKET_PATH:
        listeners.append(f"unix:{SOCKET_PATH}")
    if BIND_HOST:
        listeners.append(f"tcp://{BIND_HOST}:{BIND_PORT}")
    print(f"[daemon] listening on {', '.join(listeners)}", flush=True)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()

    for s in sites:
        await s.stop()
    await runner.cleanup()
    print("[daemon] stopped", flush=True)


if __name__ == "__main__":
    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        pass

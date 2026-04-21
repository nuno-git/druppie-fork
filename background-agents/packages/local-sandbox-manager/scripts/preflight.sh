#!/bin/sh
# Preflight check for the local sandbox-manager container.
#
# The sandbox-manager's entire purpose is shelling out to the host Docker
# daemon via /var/run/docker.sock. If the bind mount silently became a
# directory (compose default when DOCKER_SOCK points at a path that did not
# exist at up time) or the daemon is down, the service comes up "healthy"
# on its HTTP port but fails every sandbox spawn with
# "Cannot connect to the Docker daemon". Fail fast instead.
set -e

SOCK=/var/run/docker.sock

if [ ! -S "$SOCK" ]; then
  echo "[preflight] FATAL: $SOCK is not a unix socket." >&2
  echo "[preflight] The sandbox-manager needs the host docker.sock bind-mounted." >&2
  echo "[preflight] Check DOCKER_SOCK in your .env — the source path must exist on the host AS A SOCKET when compose up runs." >&2
  echo "[preflight] Typical host paths: /run/docker.sock (system docker), /run/user/<uid>/docker.sock (rootless)." >&2
  ls -la "$SOCK" >&2 || true
  exit 1
fi

# Ping the daemon to make sure it actually responds, not just that a socket file exists.
# Uses python3 stdlib (guaranteed in the base image) rather than curl, which is
# only present here as a side effect of the docker-cli apt setup.
if ! python3 - "$SOCK" <<'PY'
import socket, sys
sock_path = sys.argv[1]
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.settimeout(5)
try:
    s.connect(sock_path)
    s.sendall(b"GET /_ping HTTP/1.0\r\nHost: localhost\r\n\r\n")
    resp = s.recv(64)
except OSError as e:
    print(f"[preflight] connect/ping error: {e}", file=sys.stderr)
    sys.exit(1)
finally:
    s.close()
sys.exit(0 if resp.startswith((b"HTTP/1.0 200", b"HTTP/1.1 200")) else 1)
PY
then
  echo "[preflight] FATAL: $SOCK exists but the Docker daemon is not responding to /_ping." >&2
  echo "[preflight] The host daemon is likely down, or the container's user can't read the socket." >&2
  exit 1
fi

echo "[preflight] docker.sock OK — starting sandbox-manager."
exec "$@"

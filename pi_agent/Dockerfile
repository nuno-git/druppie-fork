# ─────────────────────────────────────────────────────────────────────────────
# Druppie Pi Agent — Dockerfile
#
# Multi-stage build that produces a container capable of:
#   1. Running the Pi coding agent CLI
#   2. Launching sandbox containers via the host Docker daemon
#      (Docker socket must be mounted from the host)
#
# The container needs Docker CLI installed so it can `docker run` sandbox
# microVMs. The actual Docker daemon runs on the host — we only mount the
# socket.
#
# ─── Build ───────────────────────────────────────────────────────────────────
#
#   # Build sandbox + push images first (required at runtime)
#   docker build -t oneshot-sandbox:latest  sandbox/
#   docker build -t oneshot-push-sandbox:latest  push-sandbox/
#
#   # Then build this image
#   docker build -t druppie-pi-agent .
#
# ─── Run ─────────────────────────────────────────────────────────────────────
#
#   docker run --rm -it \
#     -v /var/run/docker.sock:/var/run/docker.sock \
#     --env-file .env \
#     druppie-pi-agent
#
# In Druppie (compose) mode, also set:
#   -e PI_AGENT_SANDBOX_NETWORK=druppie_default
#   -v druppie_bundle_volume:/app/pi_agent_bundles
#
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: Build TypeScript ────────────────────────────────────────────────
FROM node:22-slim AS builder

WORKDIR /app

# Install deps first (layer cache)
COPY package.json package-lock.json* ./
RUN npm install

# Copy source and compile
COPY tsconfig.json ./
COPY src/ src/
RUN npx tsc

# ── Stage 2: Runtime ─────────────────────────────────────────────────────────
FROM node:22-slim

ENV DEBIAN_FRONTEND=noninteractive

# Docker CLI — needed to launch sandbox containers on the host daemon.
# We only need the client binary, not dockerd itself.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg \
        -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc \
    && echo "deb [arch=$(dpkg --print-architecture) \
        signed-by=/etc/apt/keyrings/docker.asc] \
        https://download.docker.com/linux/debian bookworm stable" \
        > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends docker-ce-cli \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy node_modules from builder (includes pi SDK)
COPY --from=builder /app/node_modules/ node_modules/

# Copy compiled JS
COPY --from=builder /app/dist/ dist/

# Copy static project files
COPY package.json ./
COPY .pi/ .pi/
COPY sandbox/ sandbox/
COPY push-sandbox/ push-sandbox/
COPY scripts/ scripts/

# Named-volume mount point for bundle exchange with sandboxes
# (used when PI_AGENT_BUNDLE_VOLUME is set)
RUN mkdir -p /app/pi_agent_bundles

# Pi stores sessions under ~/.pi/agent by default; keep it in-app for containers
ENV PI_CODING_AGENT_DIR=/app/.pi/agent \
    HOME=/root

# The CLI doesn't expose a port, but sandboxes listen on 8000 internally.
# No EXPOSE needed — this container talks to sandboxes over Docker networking.

ENTRYPOINT ["node", "dist/cli.js"]
CMD ["--help"]

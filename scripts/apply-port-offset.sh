#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${ENV_FILE:-.env}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENV_PATH="${PROJECT_ROOT}/${ENV_FILE}"

if [ ! -f "$ENV_PATH" ]; then
  echo "ERROR: $ENV_PATH not found" >&2
  exit 1
fi

OFFSET="${PORT_OFFSET:-0}"
if [ -n "${PORT_OFFSET:-}" ] && grep -q "^PORT_OFFSET=" "$ENV_PATH" 2>/dev/null; then
  OFFSET="$(grep "^PORT_OFFSET=" "$ENV_PATH" | head -1 | cut -d= -f2-)"
fi
OFFSET="${OFFSET:-0}"

declare -A BASE_PORTS
BASE_PORTS=(
  [BACKEND_PORT]=8000
  [FRONTEND_PORT]=5173
  [KEYCLOAK_PORT]=8080
  [GITEA_PORT]=3000
  [GITEA_SSH_PORT]=2222
  [DRUPPIE_DB_PORT]=5432
  [ADMINER_PORT]=8080
  [MCP_CODING_PORT]=9001
  [MCP_DOCKER_PORT]=9002
  [MCP_HITL_PORT]=9003
  [MCP_FILESEARCH_PORT]=9004
  [MCP_WEB_PORT]=9005
  [MCP_ARCHIMATE_PORT]=9006
  [MCP_REGISTRY_PORT]=9007
  [MCP_VISION_PORT]=9008
  [MCP_LLM_PORT]=9009
)

set_count=0
skipped_count=0

for var in "${!BASE_PORTS[@]}"; do
  base="${BASE_PORTS[$var]}"
  computed=$((base + OFFSET))

  existing="$(grep "^${var}=" "$ENV_PATH" 2>/dev/null | head -1 | cut -d= -f2- || true)"
  if [ -n "$existing" ]; then
    echo "  PRESERVED: ${var}=${existing} (already set)"
    ((skipped_count++)) || true
    continue
  fi

  echo "${var}=${computed}" >> "$ENV_PATH"
  echo "  SET: ${var}=${computed} (base ${base} + offset ${OFFSET})"
  ((set_count++)) || true
done

echo ""
echo "Done: ${set_count} ports set, ${skipped_count} ports preserved."
echo "PORT_OFFSET=${OFFSET}"

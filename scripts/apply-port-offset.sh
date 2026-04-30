#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENV_FILE="${PROJECT_ROOT}/.env"

if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: $ENV_FILE not found" >&2
  echo "  cp .env.example .env  first" >&2
  exit 1
fi

OFFSET="$(grep '^PORT_OFFSET=' "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true)"
OFFSET="${OFFSET:-0}"

if [ "$OFFSET" -eq 0 ]; then
  echo "PORT_OFFSET=0 — nothing to do."
  exit 0
fi

declare -A BASE_PORTS
BASE_PORTS=(
  [BACKEND_PORT]=8000
  [FRONTEND_PORT]=5173
  [KEYCLOAK_PORT]=8080
  [GITEA_PORT]=3000
  [GITEA_SSH_PORT]=2222
  [DRUPPIE_DB_PORT]=5432
  [ADMINER_PORT]=8081
  [MCP_CODING_PORT]=9001
  [MCP_DOCKER_PORT]=9002
  [MCP_FILESEARCH_PORT]=9004
  [MCP_WEB_PORT]=9005
  [MCP_ARCHIMATE_PORT]=9006
  [MCP_REGISTRY_PORT]=9007
  [MCP_VISION_PORT]=9008
  [MCP_LLM_PORT]=9009
)

echo "Applying PORT_OFFSET=+${OFFSET} ..."
echo ""

for var in BACKEND_PORT FRONTEND_PORT KEYCLOAK_PORT GITEA_PORT GITEA_SSH_PORT \
           DRUPPIE_DB_PORT ADMINER_PORT MCP_CODING_PORT MCP_DOCKER_PORT \
           MCP_FILESEARCH_PORT MCP_WEB_PORT MCP_ARCHIMATE_PORT \
           MCP_REGISTRY_PORT MCP_VISION_PORT MCP_LLM_PORT; do
  base="${BASE_PORTS[$var]}"
  computed=$((base + OFFSET))

  if grep -q "^${var}=" "$ENV_FILE"; then
    sed "s|^${var}=.*|${var}=${computed}|" "$ENV_FILE" > "${ENV_FILE}.tmp" && mv "${ENV_FILE}.tmp" "$ENV_FILE"
  elif grep -q "^# *${var}=" "$ENV_FILE"; then
    sed "s|^# *${var}=.*|${var}=${computed}|" "$ENV_FILE" > "${ENV_FILE}.tmp" && mv "${ENV_FILE}.tmp" "$ENV_FILE"
  else
    echo "${var}=${computed}" >> "$ENV_FILE"
  fi

  echo "  ${var}=${computed}  (${base} + ${OFFSET})"
done

echo ""
echo "Done. Run 'docker compose up -d' to apply."

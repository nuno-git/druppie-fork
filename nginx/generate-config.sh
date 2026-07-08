#!/usr/bin/env bash
# ==========================================================================
# generate-config.sh — Generate nginx config from template
#
# Usage:
#   ./nginx/generate-config.sh \
#     --druppie-domain druppie.example.com \
#     --gitea-domain gitea.example.com
#
# All flags have sensible defaults — see below.
# ==========================================================================
set -euo pipefail

# --- Defaults ---------------------------------------------------------------
DRUPPIE_DOMAIN=""
GITEA_DOMAIN=""
SSL_CERT_DIR=""
BACKEND_PORT=8100
FRONTEND_PORT=5273
KEYCLOAK_PORT=8180
GITEA_PORT=3100
OAUTH2_PROXY_PORT=4180
OUTPUT=""

# --- Parse arguments --------------------------------------------------------
usage() {
  cat <<'EOF'
Usage: generate-config.sh [OPTIONS]

Options:
  --druppie-domain DOMAIN     Druppie frontend/backend domain (required)
  --gitea-domain DOMAIN       Gitea subdomain (required)
  --ssl-cert-dir PATH         SSL certificate directory
                              Default: /etc/letsencrypt/live/<base-domain>
  --backend-port PORT         Backend port (default: 8100)
  --frontend-port PORT        Frontend port (default: 5273)
  --keycloak-port PORT        Keycloak port (default: 8180)
  --gitea-port PORT           Gitea port (default: 3100)
  --oauth2-proxy-port PORT    oauth2-proxy port (default: 4180)
  --output FILE               Output file path
                              Default: <script-dir>/druppie-prod.conf
  -h, --help                  Show this help message

Examples:
  # Minimal (auto-detects SSL cert dir from base domain)
  ./nginx/generate-config.sh \\
    --druppie-domain druppie.example.com \\
    --gitea-domain gitea.example.com

  # Full control
  ./nginx/generate-config.sh \\
    --druppie-domain druppie.example.com \\
    --gitea-domain gitea.example.com \\
    --ssl-cert-dir /etc/letsencrypt/live/example.com \\
    --backend-port 8100 \\
    --frontend-port 5273
EOF
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --druppie-domain)    DRUPPIE_DOMAIN="$2"; shift 2 ;;
    --gitea-domain)      GITEA_DOMAIN="$2"; shift 2 ;;
    --ssl-cert-dir)      SSL_CERT_DIR="$2"; shift 2 ;;
    --backend-port)      BACKEND_PORT="$2"; shift 2 ;;
    --frontend-port)     FRONTEND_PORT="$2"; shift 2 ;;
    --keycloak-port)     KEYCLOAK_PORT="$2"; shift 2 ;;
    --gitea-port)        GITEA_PORT="$2"; shift 2 ;;
    --oauth2-proxy-port) OAUTH2_PROXY_PORT="$2"; shift 2 ;;
    --output)            OUTPUT="$2"; shift 2 ;;
    -h|--help)           usage ;;
    *) echo "ERROR: Unknown option: $1" >&2; exit 1 ;;
  esac
done

# --- Validate required args -------------------------------------------------
if [[ -z "$DRUPPIE_DOMAIN" ]]; then
  echo "ERROR: --druppie-domain is required" >&2
  exit 1
fi

if [[ -z "$GITEA_DOMAIN" ]]; then
  echo "ERROR: --gitea-domain is required" >&2
  exit 1
fi

# --- Derive SSL cert dir from druppie domain if not provided ----------------
# Strategy: strip subdomain prefixes to get the base domain for cert path.
# e.g. druppie.example.com -> example.com, example.com -> example.com
if [[ -z "$SSL_CERT_DIR" ]]; then
  # Count dots. 2+ dots = has subdomain(s), strip first part.
  DOT_COUNT=$(echo "$DRUPPIE_DOMAIN" | tr -cd '.' | wc -c)
  if [[ "$DOT_COUNT" -ge 2 ]]; then
    BASE_DOMAIN="${DRUPPIE_DOMAIN#*.}"
  else
    BASE_DOMAIN="$DRUPPIE_DOMAIN"
  fi
  SSL_CERT_DIR="/etc/letsencrypt/live/${BASE_DOMAIN}"
fi

# --- Resolve paths ----------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="${SCRIPT_DIR}/druppie-prod.conf.template"

if [[ -z "$OUTPUT" ]]; then
  OUTPUT="${SCRIPT_DIR}/druppie-prod.conf"
fi

if [[ ! -f "$TEMPLATE" ]]; then
  echo "ERROR: Template not found: $TEMPLATE" >&2
  exit 1
fi

# --- Generate config --------------------------------------------------------
echo "Generating nginx config..."
echo "  Druppie domain:  ${DRUPPIE_DOMAIN}"
echo "  Gitea domain:    ${GITEA_DOMAIN}"
echo "  SSL cert dir:    ${SSL_CERT_DIR}"
echo "  Backend:         127.0.0.1:${BACKEND_PORT}"
echo "  Frontend:        127.0.0.1:${FRONTEND_PORT}"
echo "  Keycloak:        127.0.0.1:${KEYCLOAK_PORT}"
echo "  Gitea:           127.0.0.1:${GITEA_PORT}"
echo "  oauth2-proxy:    127.0.0.1:${OAUTH2_PROXY_PORT}"

sed \
  -e "s|__DRUPPIE_DOMAIN__|${DRUPPIE_DOMAIN}|g" \
  -e "s|__GITEA_DOMAIN__|${GITEA_DOMAIN}|g" \
  -e "s|__SSL_CERT_PATH__|${SSL_CERT_DIR}|g" \
  -e "s|__BACKEND_PORT__|${BACKEND_PORT}|g" \
  -e "s|__FRONTEND_PORT__|${FRONTEND_PORT}|g" \
  -e "s|__KEYCLOAK_PORT__|${KEYCLOAK_PORT}|g" \
  -e "s|__GITEA_PORT__|${GITEA_PORT}|g" \
  -e "s|__OAUTH2_PROXY_PORT__|${OAUTH2_PROXY_PORT}|g" \
  "$TEMPLATE" > "$OUTPUT"

echo "  Output:          ${OUTPUT}"
echo "Done."

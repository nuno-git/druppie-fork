#!/bin/sh
set -e

# Replace build-time placeholders with runtime environment variables
# Vite bakes env vars at build time; this lets us configure at deploy time
for f in /app/dist/assets/*.js; do
  sed -i \
    -e "s|__VITE_API_URL__|${VITE_API_URL:-http://localhost:8000}|g" \
    -e "s|__VITE_KEYCLOAK_URL__|${VITE_KEYCLOAK_URL:-http://localhost:8080}|g" \
    -e "s|__VITE_KEYCLOAK_REALM__|${VITE_KEYCLOAK_REALM:-druppie}|g" \
    -e "s|__VITE_KEYCLOAK_CLIENT_ID__|${VITE_KEYCLOAK_CLIENT_ID:-druppie-frontend}|g" \
    -e "s|__VITE_GITEA_URL__|${VITE_GITEA_URL:-http://localhost:3000}|g" \
    "$f"
done

exec "$@"

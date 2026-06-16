#!/bin/sh
set -e

# Replace build-time placeholders with runtime environment variables.
# Vite bakes env vars at build time; this lets us configure at deploy time.

# Escape characters that are special on sed's replacement side (\, &, and the
# | delimiter) so values containing them don't corrupt the substitution.
esc() {
  printf '%s' "$1" | sed -e 's/[\\&|]/\\&/g'
}

API_URL=$(esc "${VITE_API_URL:-http://localhost:8000}")
KEYCLOAK_URL=$(esc "${VITE_KEYCLOAK_URL:-http://localhost:8080}")
KEYCLOAK_REALM=$(esc "${VITE_KEYCLOAK_REALM:-druppie}")
KEYCLOAK_CLIENT_ID=$(esc "${VITE_KEYCLOAK_CLIENT_ID:-druppie-frontend}")
GITEA_URL=$(esc "${VITE_GITEA_URL:-http://localhost:3000}")

found=0
for f in /app/dist/assets/*.js; do
  [ -e "$f" ] || continue
  found=1
  sed -i \
    -e "s|__VITE_API_URL__|${API_URL}|g" \
    -e "s|__VITE_KEYCLOAK_URL__|${KEYCLOAK_URL}|g" \
    -e "s|__VITE_KEYCLOAK_REALM__|${KEYCLOAK_REALM}|g" \
    -e "s|__VITE_KEYCLOAK_CLIENT_ID__|${KEYCLOAK_CLIENT_ID}|g" \
    -e "s|__VITE_GITEA_URL__|${GITEA_URL}|g" \
    "$f"
done

[ "$found" = 1 ] || echo "docker-entrypoint: warning: no JS assets matched /app/dist/assets/*.js" >&2

exec "$@"

#!/bin/sh
# Druppie Platform - Init Container Entrypoint
# Runs Keycloak and Gitea setup scripts on first launch.
# Uses a marker file to skip subsequent runs.

set -e

MARKER_FILE="/init-marker/.initialized"

if [ -f "$MARKER_FILE" ]; then
    echo "=== Init already completed (marker found) ==="
    echo "To re-run initialization, remove the druppie_init_marker volume:"
    echo "  docker volume rm druppie_init_marker"
    exit 0
fi

echo "=============================================="
echo "  Druppie Platform - First-Time Initialization"
echo "=============================================="
echo ""

# Step 1: Configure Keycloak
echo "--- Step 1/2: Configuring Keycloak ---"
python /app/scripts/setup_keycloak.py
echo ""

# Step 2: Configure Gitea
echo "--- Step 2/2: Configuring Gitea ---"
python /app/scripts/setup_gitea.py
echo ""

# Mark initialization as complete
touch "$MARKER_FILE"

echo "=============================================="
echo "  Initialization Complete!"
echo "=============================================="
echo ""
echo "If GITEA_TOKEN was generated, you may need to restart"
echo "services to pick up the new token:"
echo "  docker compose restart mcp-coding"
echo ""

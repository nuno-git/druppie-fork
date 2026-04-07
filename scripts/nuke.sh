#!/bin/bash
# Druppie Platform - Full Nuke & Rebuild
# =======================================
# Destroys EVERYTHING (containers, volumes, images) and rebuilds from scratch.
# As if you just cloned the repo and set up for the first time.
#
# Dockerized usage (recommended):
#   docker compose --profile nuke run --rm nuke
#   START_AFTER=false docker compose --profile nuke run --rm nuke   # nuke only, don't start
#
# Direct usage:
#   ./scripts/nuke.sh [--stop]

set -e

# When running inside the container, /project is the repo root
if [ -d /project ]; then
    cd /project
else
    cd "$(dirname "$0")/.."
fi

START_AFTER="${START_AFTER:-true}"
if [ "$1" = "--stop" ]; then
    START_AFTER="false"
fi

echo "=============================================="
echo "  Druppie Platform - FULL NUKE & REBUILD"
echo "=============================================="
echo ""
echo "This will destroy EVERYTHING and rebuild from scratch:"
echo "  - All containers"
echo "  - All data volumes (databases, Keycloak, Gitea, workspace)"
echo "  - All built Docker images (backend, frontend, MCP modules, sandbox)"
echo "  - Init marker (forces re-initialization)"
echo ""

# Step 1: Stop all containers and remove volumes
echo "--- Step 1: Stopping all containers and removing volumes ---"
docker compose \
    --profile dev --profile prod --profile infra \
    --profile init --profile reset-db --profile reset-hard \
    --profile reset-cache --profile scan-cache \
    down -v --remove-orphans || true
echo "  Done"
echo ""

# Step 2: Remove any remaining named volumes (catches volumes that survived Step 1)
echo "--- Step 2: Cleaning up remaining volumes ---"
VOLUMES=$(docker compose \
    --profile dev --profile prod --profile infra \
    --profile init --profile reset-db --profile reset-hard \
    --profile reset-cache --profile scan-cache \
    config --volumes 2>/dev/null) || true

for vol in $VOLUMES; do
    if docker volume inspect "$vol" >/dev/null 2>&1; then
        echo "  Removing volume: $vol"
        docker volume rm "$vol" 2>/dev/null || echo "  Warning: Could not remove $vol"
    fi
done
echo "  Done"
echo ""

# Step 3: Remove all locally built images (forces full rebuild)
echo "--- Step 3: Removing built Docker images ---"
IMAGES=$(docker compose \
    --profile dev --profile prod --profile infra \
    --profile init --profile reset-db --profile reset-hard \
    --profile reset-cache --profile scan-cache \
    config --images 2>/dev/null | sort -u) || true

for img in $IMAGES; do
    # Skip upstream images - only remove locally built ones
    case "$img" in
        postgres:*|quay.io/*|docker:*) continue ;;
    esac
    if docker image inspect "$img" >/dev/null 2>&1; then
        echo "  Removing image: $img"
        docker rmi "$img" 2>/dev/null || echo "  Warning: Could not remove $img"
    fi
done
echo "  Done"
echo ""

# Step 4: Ensure submodules are initialized
echo "--- Step 4: Initializing git submodules ---"
if command -v git >/dev/null 2>&1 && [ -d .git ]; then
    git submodule update --init --recursive
    echo "  Done"
else
    echo "  Skipped (no git available in container)"
fi
echo ""

if [ "$START_AFTER" = "true" ]; then
    # Step 5: Purge build cache (ensures truly clean rebuild)
    echo "--- Step 5: Purging Docker build cache ---"
    docker builder prune -af 2>/dev/null || true
    echo "  Done"
    echo ""

    # Step 6: Build and start everything from scratch
    echo "--- Step 6: Building and starting dev environment ---"
    echo "  This will take a few minutes on first build..."
    echo ""
    docker compose --profile dev --profile init up -d --build
    echo ""

    echo ""
    echo "=============================================="
    echo "  Nuke & Rebuild Complete!"
    echo "=============================================="
    echo ""
    echo "Services are starting up. Give it a minute for initialization."
    echo ""
    echo "  Frontend:       http://localhost:${FRONTEND_PORT:-5273}"
    echo "  API Docs:       http://localhost:${BACKEND_PORT:-8100}/docs"
    echo "  Keycloak Admin: http://localhost:${KEYCLOAK_PORT:-8180}"
    echo "  Gitea:          http://localhost:${GITEA_PORT:-3100}"
    echo ""
    echo "Check logs:  docker compose --profile dev logs -f"
else
    echo "=============================================="
    echo "  Nuke Complete (stop mode)"
    echo "=============================================="
    echo ""
    echo "Everything has been removed. To start fresh:"
    echo "  docker compose --profile dev --profile init up -d --build"
fi

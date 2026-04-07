#!/bin/sh
# Druppie Platform - Hard Reset Script
# Removes all data volumes and re-runs initialization.
# This script runs inside the reset-hard container.

set -e

echo "=============================================="
echo "  Druppie Platform - HARD RESET"
echo "=============================================="
echo ""
echo "WARNING: This will destroy ALL data including:"
echo "  - Application database"
echo "  - Keycloak configuration and users"
echo "  - Gitea repositories and configuration"
echo "  - Workspace files"
echo ""

cd /project

# Rootless Docker fix: when this script runs inside a container, compose resolves relative
# volume paths (./druppie/...) to /project/druppie/... on the host. Rootless Docker can't
# mkdir /project at the system root. Fix: create a symlink so compose resolves paths to the
# actual host directory, which the daemon can access.
if [ -n "$HOST_PROJECT_DIR" ] && [ "$HOST_PROJECT_DIR" != "/project" ]; then
    mkdir -p "$(dirname "$HOST_PROJECT_DIR")"
    ln -sf /project "$HOST_PROJECT_DIR"
    cd "$HOST_PROJECT_DIR"
fi
COMPOSE="docker compose"

# Step 1: Stop all services and remove volumes
echo "--- Step 1: Stopping all services and removing volumes ---"
$COMPOSE --profile dev --profile prod --profile infra down -v 2>/dev/null || true
echo "  Done"
echo ""

# Step 2: Remove any remaining druppie volumes (in case they were external)
echo "--- Step 2: Cleaning up any remaining volumes ---"
for vol in druppie_new_postgres druppie_new_keycloak_postgres druppie_new_gitea_postgres druppie_new_gitea druppie_new_workspace druppie_new_dataset druppie_init_marker druppie_sandbox_dep_cache druppie_cache_scan_results; do
    if docker volume inspect "$vol" >/dev/null 2>&1; then
        echo "  Removing volume: $vol"
        docker volume rm "$vol" 2>/dev/null || echo "  Warning: Could not remove $vol"
    fi
done
echo ""

# Step 3: Start infrastructure
echo "--- Step 3: Starting infrastructure ---"
$COMPOSE --profile infra up -d
echo ""

# Step 4: Wait for services to be healthy
echo "--- Step 4: Waiting for services to be healthy ---"

echo "  Waiting for PostgreSQL..."
for i in $(seq 1 30); do
    if docker exec druppie-new-db pg_isready -U druppie >/dev/null 2>&1; then
        echo "  PostgreSQL is ready"
        break
    fi
    sleep 2
done

echo "  Waiting for Keycloak..."
for i in $(seq 1 30); do
    if docker exec druppie-new-keycloak curl -sf http://localhost:8080/health/ready >/dev/null 2>&1; then
        echo "  Keycloak is ready"
        break
    fi
    sleep 3
done

echo "  Waiting for Gitea..."
for i in $(seq 1 30); do
    if docker exec druppie-new-gitea curl -sf http://localhost:3000/api/healthz >/dev/null 2>&1; then
        echo "  Gitea is ready"
        break
    fi
    sleep 3
done
echo ""

# Step 5: Run initialization (Keycloak + Gitea setup)
echo "--- Step 5: Running initialization ---"
python /app/scripts/setup_keycloak.py
python /app/scripts/setup_gitea.py
echo ""

echo "=============================================="
echo "  Hard Reset Complete!"
echo "=============================================="
echo ""
echo "Infrastructure is running. To start the application:"
echo "  docker compose --profile dev up -d    # Development mode"
echo "  docker compose --profile prod up -d   # Production mode"
echo ""

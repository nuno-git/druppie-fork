#!/bin/sh
# Druppie Platform - Hard Reset Script
# Removes all data volumes and re-runs initialization.
# This script runs inside the reset-hard container.

set -e

# Docker Compose project name, used as the prefix for volume and container names
# (Compose names resources as <project>_<volume> and <project>-<service>-<ordinal>).
# Sourced from the COMPOSE_PROJECT_NAME env var set by the reset-hard service.
P="${COMPOSE_PROJECT_NAME:-druppie}"

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

# Compose project name — prefixes volume names (<P>_postgres) and container names
# (<P>-<service>-1). Must match the project the stack was actually started with.
P="${COMPOSE_PROJECT_NAME:-druppie}"

# Step 1: Stop all services and remove volumes
echo "--- Step 1: Stopping all services and removing volumes ---"
$COMPOSE --profile dev --profile prod --profile infra down -v 2>/dev/null || true
echo "  Done"
echo ""

# Step 2: Remove any remaining instance volumes (in case they were external)
echo "--- Step 2: Cleaning up instance volumes ---"
for vol in ${P}_postgres ${P}_keycloak_postgres ${P}_gitea_postgres \
           ${P}_gitea_data ${P}_workspace ${P}_dataset \
           ${P}_init_marker ${P}_sandbox_dep_cache ${P}_sandbox_bundles; do
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
    if $COMPOSE exec -T db pg_isready -U druppie >/dev/null 2>&1; then
        echo "  PostgreSQL is ready"
        break
    fi
    sleep 2
done

echo "  Waiting for Keycloak..."
for i in $(seq 1 30); do
    if $COMPOSE exec -T keycloak curl -sf http://localhost:8080/health/ready >/dev/null 2>&1; then
        echo "  Keycloak is ready"
        break
    fi
    sleep 3
done

echo "  Waiting for Gitea..."
for i in $(seq 1 30); do
    if $COMPOSE exec -T gitea curl -sf http://localhost:3000/api/healthz >/dev/null 2>&1; then
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

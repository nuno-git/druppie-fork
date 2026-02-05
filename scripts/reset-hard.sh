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

# Step 1: Stop all druppie service containers (except this one)
echo "--- Step 1: Stopping service containers ---"
CONTAINERS=$(docker ps -q --filter "network=druppie-new-network" --filter "label=com.docker.compose.project" 2>/dev/null || true)
SELF_ID=$(cat /proc/self/cgroup 2>/dev/null | grep -o '[a-f0-9]\{64\}' | head -1 || hostname)

for container in $CONTAINERS; do
    CONTAINER_ID=$(docker inspect --format '{{.Id}}' "$container" 2>/dev/null || echo "")
    if [ -n "$CONTAINER_ID" ] && [ "${CONTAINER_ID#*$SELF_ID}" = "$CONTAINER_ID" ]; then
        CONTAINER_NAME=$(docker inspect --format '{{.Name}}' "$container" 2>/dev/null | sed 's/^\///')
        echo "  Stopping: $CONTAINER_NAME"
        docker stop "$container" 2>/dev/null || true
        docker rm "$container" 2>/dev/null || true
    fi
done
echo ""

# Step 2: Remove all druppie volumes
echo "--- Step 2: Removing data volumes ---"
for vol in druppie_new_postgres druppie_new_keycloak_postgres druppie_new_gitea_postgres druppie_new_gitea druppie_new_workspace druppie_new_dataset druppie_init_marker; do
    if docker volume inspect "$vol" >/dev/null 2>&1; then
        echo "  Removing volume: $vol"
        docker volume rm "$vol" 2>/dev/null || echo "  Warning: Could not remove $vol (may be in use)"
    fi
done
echo ""

# Step 3: Restart infrastructure using docker compose
echo "--- Step 3: Restarting infrastructure ---"
cd /project
docker compose --profile infra up -d
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
for i in $(seq 1 60); do
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

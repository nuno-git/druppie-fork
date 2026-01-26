#!/bin/bash
# =============================================================================
# Druppie Governance Platform - Setup Script
# =============================================================================
# This script sets up the complete Druppie infrastructure:
# - Docker network
# - Keycloak (identity provider)
# - Gitea (git server)
# - Druppie Backend (FastAPI)
# - Druppie Frontend (Vite + React)
# - MCP Servers (Coding, Docker, HITL)
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log() { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# Detect Docker Compose command (v1 or v2)
if command -v docker-compose >/dev/null 2>&1; then
    DOCKER_COMPOSE="docker-compose"
elif docker compose version >/dev/null 2>&1; then
    DOCKER_COMPOSE="docker compose"
else
    DOCKER_COMPOSE="docker compose"  # Default, will fail later with helpful error
fi

# Use the druppie directory docker-compose.yml
COMPOSE_FILE="druppie/docker-compose.yml"

# =============================================================================
# CONFIGURATION
# =============================================================================
export EXTERNAL_HOST="${EXTERNAL_HOST:-localhost}"
export KEYCLOAK_DB_PASSWORD="${KEYCLOAK_DB_PASSWORD:-keycloak_secret}"
export GITEA_DB_PASSWORD="${GITEA_DB_PASSWORD:-gitea_secret}"
export DRUPPIE_DB_PASSWORD="${DRUPPIE_DB_PASSWORD:-druppie_secret}"
export KEYCLOAK_ADMIN="${KEYCLOAK_ADMIN:-admin}"
export KEYCLOAK_ADMIN_PASSWORD="${KEYCLOAK_ADMIN_PASSWORD:-admin}"
export KEYCLOAK_CLIENT_SECRET="${KEYCLOAK_CLIENT_SECRET:-$(openssl rand -hex 32)}"
export GITEA_CLIENT_SECRET="${GITEA_CLIENT_SECRET:-$(openssl rand -hex 32)}"
export GITEA_SECRET_KEY="${GITEA_SECRET_KEY:-$(openssl rand -hex 32)}"

# Save generated secrets to .env
save_env() {
    cat > .env << EOF
# Druppie Governance Platform - Environment Variables
# Generated on $(date)

# External hostname (change for production)
EXTERNAL_HOST=${EXTERNAL_HOST}

# Database passwords
KEYCLOAK_DB_PASSWORD=${KEYCLOAK_DB_PASSWORD}
GITEA_DB_PASSWORD=${GITEA_DB_PASSWORD}
DRUPPIE_DB_PASSWORD=${DRUPPIE_DB_PASSWORD}

# Keycloak admin credentials
KEYCLOAK_ADMIN=${KEYCLOAK_ADMIN}
KEYCLOAK_ADMIN_PASSWORD=${KEYCLOAK_ADMIN_PASSWORD}

# OAuth2 client secrets
KEYCLOAK_CLIENT_SECRET=${KEYCLOAK_CLIENT_SECRET}
GITEA_CLIENT_SECRET=${GITEA_CLIENT_SECRET}
GITEA_SECRET_KEY=${GITEA_SECRET_KEY}

# LLM Configuration (configure one of these)
LLM_PROVIDER=zai
ZAI_API_KEY=${ZAI_API_KEY:-}
ZAI_MODEL=GLM-4.7
ZAI_BASE_URL=https://api.z.ai/api/coding/paas/v4
OLLAMA_HOST=http://host.docker.internal:11434
OLLAMA_MODEL=qwen2.5:7b

# MCP Microservices (HITL is built into backend)
USE_MCP_MICROSERVICES=true
MCP_CODING_URL=http://mcp-coding:9001
MCP_DOCKER_URL=http://mcp-docker:9002
EOF
    success "Environment saved to .env"
}

# Helper function for docker compose
compose() {
    $DOCKER_COMPOSE -f "$COMPOSE_FILE" "$@"
}

# =============================================================================
# MAIN SETUP FUNCTIONS
# =============================================================================

check_requirements() {
    log "Checking requirements..."

    command -v docker >/dev/null 2>&1 || error "Docker is required but not installed"

    # Check for docker compose (v2) or docker-compose (v1)
    if command -v docker-compose >/dev/null 2>&1; then
        DOCKER_COMPOSE="docker-compose"
    elif docker compose version >/dev/null 2>&1; then
        DOCKER_COMPOSE="docker compose"
    else
        error "Docker Compose is required"
    fi

    log "Using: $DOCKER_COMPOSE"
    log "Compose file: $COMPOSE_FILE"

    if ! docker info >/dev/null 2>&1; then
        error "Docker daemon is not running"
    fi

    if [ ! -f "$COMPOSE_FILE" ]; then
        error "Docker compose file not found: $COMPOSE_FILE"
    fi

    success "All requirements met"
}

create_network() {
    log "Creating Docker network..."
    # Remove any existing network with wrong labels
    docker network rm druppie-network 2>/dev/null || true
    # Network will be created by docker compose
    success "Network ready"
}

start_infrastructure() {
    log "Starting infrastructure services..."
    # NOTE: Redis removed - HITL uses database directly now
    compose up -d keycloak-db gitea-db druppie-db

    log "Waiting for databases to be ready..."
    sleep 10

    # Wait for PostgreSQL (using container names from docker-compose.yml)
    until docker exec druppie-new-keycloak-db pg_isready -U keycloak 2>/dev/null; do
        log "Waiting for Keycloak DB..."
        sleep 2
    done

    until docker exec druppie-new-gitea-db pg_isready -U gitea 2>/dev/null; do
        log "Waiting for Gitea DB..."
        sleep 2
    done

    until docker exec druppie-new-db pg_isready -U druppie 2>/dev/null; do
        log "Waiting for Druppie DB..."
        sleep 2
    done

    success "Databases ready"
}

start_keycloak() {
    log "Starting Keycloak..."
    compose up -d keycloak

    log "Waiting for Keycloak to be ready (this may take a minute)..."
    until curl -sf http://localhost:8180/health/ready >/dev/null 2>&1; do
        sleep 5
        log "Still waiting for Keycloak..."
    done

    success "Keycloak is ready at http://${EXTERNAL_HOST}:8180"
}

configure_keycloak() {
    log "Configuring Keycloak realm and users..."

    # Update Keycloak URL for new port
    export KEYCLOAK_URL="http://localhost:8180"

    # Run the Keycloak configuration script
    python3 scripts/setup_keycloak.py

    success "Keycloak configured"
}

start_gitea() {
    log "Starting Gitea..."
    compose up -d gitea

    log "Waiting for Gitea to be ready..."
    until curl -sf http://localhost:3100/api/v1/version >/dev/null 2>&1; do
        sleep 3
        log "Still waiting for Gitea..."
    done

    success "Gitea is ready at http://${EXTERNAL_HOST}:3100"
}

configure_gitea() {
    log "Configuring Gitea OAuth2..."

    # Set Gitea URL for new port
    export GITEA_URL="http://localhost:3100"
    export KEYCLOAK_URL="http://localhost:8180"

    # Run the Gitea configuration script
    python3 scripts/setup_gitea.py

    success "Gitea configured"
}

start_mcp_servers() {
    log "Starting MCP microservices..."
    # NOTE: mcp-hitl removed - HITL is now built into the backend
    compose up -d mcp-coding mcp-docker

    log "Waiting for MCP servers to be ready..."
    sleep 5

    # Check if services are running
    if compose ps mcp-coding | grep -q "Up"; then
        success "Coding MCP ready (port 9001)"
    else
        warn "Coding MCP may not be ready yet"
    fi

    if compose ps mcp-docker | grep -q "Up"; then
        success "Docker MCP ready (port 9002)"
    else
        warn "Docker MCP may not be ready yet"
    fi

    success "MCP microservices started"
}

build_backend() {
    log "Building Druppie backend..."
    compose build druppie-backend
    success "Backend built"
}

build_frontend() {
    log "Building Druppie frontend..."
    compose build druppie-frontend
    success "Frontend built"
}

build_mcp_servers() {
    log "Building MCP servers..."
    # NOTE: mcp-hitl removed - HITL is now built into the backend
    compose build mcp-coding mcp-docker
    success "MCP servers built"
}

start_application() {
    log "Starting Druppie application..."
    compose up -d druppie-backend druppie-frontend

    log "Waiting for backend to be ready..."
    until curl -sf http://localhost:8100/health >/dev/null 2>&1; do
        sleep 2
        log "Still waiting for backend..."
    done

    success "Application started"
}

print_summary() {
    echo ""
    echo "============================================================================="
    echo -e "${GREEN}Druppie Governance Platform Setup Complete!${NC}"
    echo "============================================================================="
    echo ""
    echo "Services:"
    echo "  - Druppie Frontend: http://${EXTERNAL_HOST}:5273"
    echo "  - Druppie Backend:  http://${EXTERNAL_HOST}:8100"
    echo "  - Keycloak:         http://${EXTERNAL_HOST}:8180"
    echo "  - Gitea:            http://${EXTERNAL_HOST}:3100"
    echo ""
    echo "MCP Microservices:"
    echo "  - Coding MCP:  http://localhost:9001 (internal: mcp-coding:9001)"
    echo "  - Docker MCP:  http://localhost:9002 (internal: mcp-docker:9002)"
    echo "  - HITL:        Built into backend (no separate server)"
    echo ""
    echo "Default Users (Keycloak) - per goal.md:"
    echo "  - normal_user / User123!      (user role - makes requests)"
    echo "  - architect / Architect123!   (architect role - approves designs)"
    echo "  - developer / Developer123!   (developer role - approves builds)"
    echo "  - admin / Admin123!           (admin role - full access)"
    echo ""
    echo "Legacy Users:"
    echo "  - infra / Infra123!           (Infrastructure Engineer)"
    echo "  - seniordev / Developer123!   (Senior Developer)"
    echo "  - juniordev / Developer123!   (Junior Developer)"
    echo "  - productowner / Product123!  (Product Owner)"
    echo "  - compliance / Compliance123! (Compliance Officer)"
    echo "  - viewer / Viewer123!         (Viewer)"
    echo ""
    echo "Keycloak Admin Console:"
    echo "  - Username: ${KEYCLOAK_ADMIN}"
    echo "  - Password: ${KEYCLOAK_ADMIN_PASSWORD}"
    echo ""
    echo "Gitea Admin:"
    echo "  - Username: gitea_admin"
    echo "  - Password: GiteaAdmin123"
    echo "  - Or login with Keycloak (click 'Sign in with Keycloak')"
    echo ""
    echo "To stop: ./setup.sh stop"
    echo "To view logs: ./setup.sh logs"
    echo "============================================================================="
}

# =============================================================================
# COMMANDS
# =============================================================================

case "${1:-all}" in
    all)
        check_requirements
        save_env
        create_network
        start_infrastructure
        start_keycloak
        configure_keycloak
        start_gitea
        configure_gitea
        build_mcp_servers
        build_backend
        build_frontend
        start_mcp_servers
        start_application
        print_summary
        ;;
    infra)
        check_requirements
        save_env
        create_network
        start_infrastructure
        start_keycloak
        start_gitea
        ;;
    configure)
        configure_keycloak
        configure_gitea
        ;;
    mcp)
        build_mcp_servers
        start_mcp_servers
        ;;
    app)
        build_backend
        build_frontend
        start_application
        ;;
    start)
        compose up -d
        ;;
    stop)
        compose down
        ;;
    restart)
        compose down
        compose up -d
        ;;
    logs)
        compose logs -f "${2:-}"
        ;;
    clean)
        warn "This will delete all data!"
        read -p "Are you sure? (y/N) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            compose down -v
            docker network rm druppie-network 2>/dev/null || true
            success "Cleaned up"
        fi
        ;;
    status)
        compose ps
        ;;
    build)
        log "Building all services..."
        compose build
        success "All services built"
        ;;
    *)
        echo "Usage: $0 {all|infra|configure|mcp|app|start|stop|restart|logs|clean|status|build}"
        echo ""
        echo "Commands:"
        echo "  all       - Full setup (default)"
        echo "  infra     - Start infrastructure only (DBs, Keycloak, Gitea)"
        echo "  configure - Configure Keycloak and Gitea"
        echo "  mcp       - Build and start MCP microservices"
        echo "  app       - Build and start application"
        echo "  start     - Start all services"
        echo "  stop      - Stop all services"
        echo "  restart   - Restart all services"
        echo "  logs      - View logs (optionally specify service)"
        echo "  clean     - Remove all containers and volumes"
        echo "  status    - Show service status"
        echo "  build     - Build all services"
        exit 1
        ;;
esac

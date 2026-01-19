#!/bin/bash
# =============================================================================
# Druppie Governance Platform - Setup Script
# =============================================================================
# This script sets up the complete Druppie infrastructure:
# - Docker network
# - Keycloak (identity provider)
# - Gitea (git server)
# - Druppie Backend (Flask API)
# - Druppie Frontend (Vite + React)
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

# =============================================================================
# CONFIGURATION
# =============================================================================
export EXTERNAL_HOST="${EXTERNAL_HOST:-localhost}"
export KEYCLOAK_DB_PASSWORD="${KEYCLOAK_DB_PASSWORD:-keycloak_secret}"
export GITEA_DB_PASSWORD="${GITEA_DB_PASSWORD:-gitea_secret}"
export DRUPPIE_DB_PASSWORD="${DRUPPIE_DB_PASSWORD:-druppie_secret}"
export KEYCLOAK_ADMIN="${KEYCLOAK_ADMIN:-admin}"
export KEYCLOAK_ADMIN_PASSWORD="${KEYCLOAK_ADMIN_PASSWORD:-admin_password}"
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

# App Configuration
FLASK_ENV=development
EOF
    success "Environment saved to .env"
}

# =============================================================================
# MAIN SETUP FUNCTIONS
# =============================================================================

check_requirements() {
    log "Checking requirements..."

    command -v docker >/dev/null 2>&1 || error "Docker is required but not installed"
    command -v docker-compose >/dev/null 2>&1 || command -v "docker compose" >/dev/null 2>&1 || error "Docker Compose is required"

    if ! docker info >/dev/null 2>&1; then
        error "Docker daemon is not running"
    fi

    success "All requirements met"
}

create_network() {
    log "Creating Docker network..."
    docker network create druppie-network 2>/dev/null || true
    success "Network ready"
}

start_infrastructure() {
    log "Starting infrastructure services..."
    docker-compose up -d keycloak-db gitea-db druppie-db redis

    log "Waiting for databases to be ready..."
    sleep 10

    # Wait for PostgreSQL
    until docker exec druppie-keycloak-db pg_isready -U keycloak 2>/dev/null; do
        log "Waiting for Keycloak DB..."
        sleep 2
    done

    until docker exec druppie-gitea-db pg_isready -U gitea 2>/dev/null; do
        log "Waiting for Gitea DB..."
        sleep 2
    done

    until docker exec druppie-app-db pg_isready -U druppie 2>/dev/null; do
        log "Waiting for Druppie DB..."
        sleep 2
    done

    success "Databases ready"
}

start_keycloak() {
    log "Starting Keycloak..."
    docker-compose up -d keycloak

    log "Waiting for Keycloak to be ready (this may take a minute)..."
    until curl -sf http://localhost:8080/health/ready >/dev/null 2>&1; do
        sleep 5
        log "Still waiting for Keycloak..."
    done

    success "Keycloak is ready at http://${EXTERNAL_HOST}:8080"
}

configure_keycloak() {
    log "Configuring Keycloak realm and users..."

    # Run the Keycloak configuration script
    python3 scripts/setup_keycloak.py

    success "Keycloak configured"
}

start_gitea() {
    log "Starting Gitea..."
    docker-compose up -d gitea registry

    log "Waiting for Gitea to be ready..."
    until curl -sf http://localhost:3000/api/v1/version >/dev/null 2>&1; do
        sleep 3
        log "Still waiting for Gitea..."
    done

    success "Gitea is ready at http://${EXTERNAL_HOST}:3000"
}

configure_gitea() {
    log "Configuring Gitea OAuth2..."

    # Run the Gitea configuration script
    python3 scripts/setup_gitea.py

    success "Gitea configured"
}

build_backend() {
    log "Building Druppie backend..."
    docker-compose build druppie-backend
    success "Backend built"
}

build_frontend() {
    log "Building Druppie frontend..."
    docker-compose build druppie-frontend
    success "Frontend built"
}

start_application() {
    log "Starting Druppie application..."
    docker-compose up -d druppie-backend druppie-frontend

    log "Waiting for backend to be ready..."
    until curl -sf http://localhost:8000/health >/dev/null 2>&1; do
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
    echo "  - Druppie Frontend: http://${EXTERNAL_HOST}:5173"
    echo "  - Druppie Backend:  http://${EXTERNAL_HOST}:8000"
    echo "  - Keycloak:         http://${EXTERNAL_HOST}:8080"
    echo "  - Gitea:            http://${EXTERNAL_HOST}:3000"
    echo "  - Docker Registry:  http://${EXTERNAL_HOST}:5000"
    echo ""
    echo "Default Users (password: see iac/users.yaml):"
    echo "  - admin / admin123       (Full access)"
    echo "  - infra / infra123       (Infrastructure Engineer)"
    echo "  - architect / arch123    (System Architect)"
    echo "  - seniordev / dev123     (Senior Developer)"
    echo "  - juniordev / dev123     (Junior Developer)"
    echo "  - productowner / po123   (Product Owner)"
    echo "  - compliance / comp123   (Compliance Officer)"
    echo "  - viewer / changeme123   (Viewer)"
    echo ""
    echo "Keycloak Admin:"
    echo "  - Username: ${KEYCLOAK_ADMIN}"
    echo "  - Password: ${KEYCLOAK_ADMIN_PASSWORD}"
    echo ""
    echo "To stop: docker-compose down"
    echo "To view logs: docker-compose logs -f"
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
        build_backend
        build_frontend
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
    app)
        build_backend
        build_frontend
        start_application
        ;;
    start)
        docker-compose up -d
        ;;
    stop)
        docker-compose down
        ;;
    restart)
        docker-compose down
        docker-compose up -d
        ;;
    logs)
        docker-compose logs -f "${2:-}"
        ;;
    clean)
        warn "This will delete all data!"
        read -p "Are you sure? (y/N) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            docker-compose down -v
            docker network rm druppie-network 2>/dev/null || true
            success "Cleaned up"
        fi
        ;;
    status)
        docker-compose ps
        ;;
    *)
        echo "Usage: $0 {all|infra|configure|app|start|stop|restart|logs|clean|status}"
        echo ""
        echo "Commands:"
        echo "  all       - Full setup (default)"
        echo "  infra     - Start infrastructure only (DBs, Keycloak, Gitea)"
        echo "  configure - Configure Keycloak and Gitea"
        echo "  app       - Build and start application"
        echo "  start     - Start all services"
        echo "  stop      - Stop all services"
        echo "  restart   - Restart all services"
        echo "  logs      - View logs (optionally specify service)"
        echo "  clean     - Remove all containers and volumes"
        echo "  status    - Show service status"
        exit 1
        ;;
esac

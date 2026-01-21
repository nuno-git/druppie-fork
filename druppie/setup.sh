#!/bin/bash
# =============================================================================
# Druppie Platform v2 - Setup Script
# =============================================================================
# This script sets up the new Druppie backend (FastAPI).
#
# Usage:
#   ./setup.sh all      - Full setup with Docker Compose
#   ./setup.sh dev      - Local development (Python + uvicorn)
#   ./setup.sh test     - Run tests
#   ./setup.sh build    - Build Docker image only
#   ./setup.sh clean    - Clean up containers and volumes
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# Detect Docker Compose command
if command -v docker-compose >/dev/null 2>&1; then
    DOCKER_COMPOSE="docker-compose"
elif docker compose version >/dev/null 2>&1; then
    DOCKER_COMPOSE="docker compose"
else
    DOCKER_COMPOSE="docker compose"
fi

# =============================================================================
# ENVIRONMENT SETUP
# =============================================================================

create_env_file() {
    if [ ! -f .env ]; then
        cat > .env << 'EOF'
# Druppie Platform v2 Environment Variables

# Database
DRUPPIE_DB_PASSWORD=druppie_secret

# Auth (set to false for production with Keycloak)
DEV_MODE=true

# LLM Configuration
# Options: mock, zai, ollama
LLM_PROVIDER=mock

# For Z.AI (cloud LLM)
ZAI_API_KEY=
ZAI_MODEL=GLM-4.7
ZAI_BASE_URL=https://api.z.ai/api/coding/paas/v4

# For Ollama (local LLM)
OLLAMA_HOST=http://host.docker.internal:11434
OLLAMA_MODEL=qwen2.5:7b

# Keycloak (when DEV_MODE=false)
KEYCLOAK_SERVER_URL=http://localhost:8080
KEYCLOAK_ISSUER_URL=http://localhost:8080
KEYCLOAK_REALM=druppie
KEYCLOAK_CLIENT_ID=druppie-backend

# Gitea (optional)
GITEA_URL=http://localhost:3000
GITEA_TOKEN=
EOF
        success "Created .env file"
    else
        log ".env file already exists"
    fi
}

# =============================================================================
# DEVELOPMENT SETUP
# =============================================================================

setup_dev() {
    log "Setting up development environment..."

    # Check Python
    if ! command -v python3 >/dev/null 2>&1; then
        error "Python 3 is required"
    fi

    # Create virtual environment if not exists
    if [ ! -d "venv" ]; then
        log "Creating virtual environment..."
        python3 -m venv venv
    fi

    # Activate and install dependencies
    log "Installing dependencies..."
    source venv/bin/activate
    pip install -q --upgrade pip
    pip install -q -r requirements.txt

    success "Development environment ready"
    echo ""
    echo "To start the server:"
    echo "  source venv/bin/activate"
    echo "  uvicorn druppie.api.main:app --reload --port 8001"
}

run_dev() {
    log "Starting development server..."

    create_env_file

    if [ ! -d "venv" ]; then
        setup_dev
    fi

    source venv/bin/activate

    # Export environment variables
    export DEV_MODE=true
    export LLM_PROVIDER=${LLM_PROVIDER:-mock}
    export PYTHONPATH="$SCRIPT_DIR/.."

    log "Server starting at http://localhost:8001"
    uvicorn druppie.api.main:app --reload --host 0.0.0.0 --port 8001
}

# =============================================================================
# DOCKER SETUP
# =============================================================================

build_image() {
    log "Building Docker image..."
    docker build -t druppie-v2:latest .
    success "Docker image built: druppie-v2:latest"
}

start_docker() {
    log "Starting Druppie v2 with Docker Compose..."

    create_env_file

    $DOCKER_COMPOSE up -d

    log "Waiting for services to be ready..."

    # Wait for backend
    until curl -sf http://localhost:8001/health >/dev/null 2>&1; do
        sleep 2
        log "Waiting for backend..."
    done

    success "Druppie v2 is ready!"
    echo ""
    echo "Services:"
    echo "  - Backend API:  http://localhost:8001"
    echo "  - API Docs:     http://localhost:8001/docs"
    echo "  - Database:     localhost:5433"
    echo "  - Redis:        localhost:6380"
    echo ""
    echo "To view logs: $DOCKER_COMPOSE logs -f"
    echo "To stop:      $DOCKER_COMPOSE down"
}

stop_docker() {
    log "Stopping Druppie v2..."
    $DOCKER_COMPOSE down
    success "Stopped"
}

# =============================================================================
# TESTING
# =============================================================================

run_tests() {
    log "Running tests..."

    if [ ! -d "venv" ]; then
        setup_dev
    fi

    source venv/bin/activate
    export PYTHONPATH="$SCRIPT_DIR/.."

    pytest tests/ -v
}

run_quick_test() {
    log "Running quick API test..."

    # Test health endpoint
    if curl -sf http://localhost:8001/health | grep -q "healthy"; then
        success "Health check passed"
    else
        error "Health check failed"
    fi

    # Test MCPs endpoint
    if curl -sf http://localhost:8001/api/mcps | grep -q "servers"; then
        success "MCPs endpoint working"
    else
        error "MCPs endpoint failed"
    fi

    # Test chat endpoint
    response=$(curl -sf -X POST http://localhost:8001/api/chat \
        -H "Content-Type: application/json" \
        -d '{"message": "Hello"}')

    if echo "$response" | grep -q "session_id"; then
        success "Chat endpoint working"
    else
        error "Chat endpoint failed"
    fi

    success "All quick tests passed!"
}

# =============================================================================
# CLEANUP
# =============================================================================

clean() {
    warn "This will delete all containers and volumes!"
    read -p "Are you sure? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        $DOCKER_COMPOSE down -v 2>/dev/null || true
        docker rm -f druppie-v2-test 2>/dev/null || true
        success "Cleaned up"
    fi
}

# =============================================================================
# MAIN
# =============================================================================

print_help() {
    echo "Druppie Platform v2 - Setup Script"
    echo ""
    echo "Usage: $0 <command>"
    echo ""
    echo "Commands:"
    echo "  all       - Full Docker Compose setup"
    echo "  dev       - Run in development mode (local Python)"
    echo "  setup     - Setup development environment only"
    echo "  build     - Build Docker image"
    echo "  start     - Start with Docker Compose"
    echo "  stop      - Stop Docker Compose services"
    echo "  test      - Run pytest tests"
    echo "  quicktest - Quick API test (requires running server)"
    echo "  clean     - Remove containers and volumes"
    echo "  logs      - View Docker Compose logs"
    echo ""
}

case "${1:-help}" in
    all)
        create_env_file
        build_image
        start_docker
        ;;
    dev)
        run_dev
        ;;
    setup)
        create_env_file
        setup_dev
        ;;
    build)
        build_image
        ;;
    start)
        start_docker
        ;;
    stop)
        stop_docker
        ;;
    test)
        run_tests
        ;;
    quicktest)
        run_quick_test
        ;;
    clean)
        clean
        ;;
    logs)
        $DOCKER_COMPOSE logs -f "${2:-}"
        ;;
    *)
        print_help
        ;;
esac

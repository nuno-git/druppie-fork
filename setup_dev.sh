#!/bin/bash
# =============================================================================
# Druppie Development Setup - Hot Reload for Backend & Frontend
# =============================================================================
#
# This script provides a fast development experience:
# - Infrastructure runs in Docker (DBs, Keycloak, Gitea, MCP servers)
# - Backend runs locally with uvicorn --reload (hot reload)
# - Frontend runs locally with Vite dev server (HMR)
#
# Usage:
#   ./setup_dev.sh          # Start everything
#   ./setup_dev.sh infra    # Start only infrastructure
#   ./setup_dev.sh backend  # Start only backend (assumes infra running)
#   ./setup_dev.sh frontend # Start only frontend (assumes backend running)
#   ./setup_dev.sh stop     # Stop everything
#   ./setup_dev.sh logs     # Show infrastructure logs
#   ./setup_dev.sh status   # Show status of all services
#
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

log() { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }
header() { echo -e "\n${CYAN}=== $1 ===${NC}\n"; }

# Detect Docker Compose command
if docker compose version >/dev/null 2>&1; then
    DOCKER_COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    DOCKER_COMPOSE="docker-compose"
else
    error "Docker Compose not found. Please install Docker."
fi

COMPOSE_FILE="druppie/docker-compose.dev.yml"

# PID files for tracking local processes
BACKEND_PID_FILE="/tmp/druppie-backend.pid"
FRONTEND_PID_FILE="/tmp/druppie-frontend.pid"

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

check_python() {
    if ! command -v python3 &> /dev/null; then
        error "Python 3 not found. Please install Python 3.11+."
    fi

    PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    log "Python version: $PYTHON_VERSION"
}

check_node() {
    if ! command -v node &> /dev/null; then
        error "Node.js not found. Please install Node.js 18+."
    fi

    NODE_VERSION=$(node -v)
    log "Node.js version: $NODE_VERSION"
}

setup_python_venv() {
    if [ ! -d "venv" ]; then
        log "Creating Python virtual environment..."
        python3 -m venv venv
    fi

    source venv/bin/activate

    log "Installing Python dependencies..."
    pip install -q -r druppie/requirements.txt
}

setup_node_modules() {
    if [ ! -d "frontend/node_modules" ]; then
        log "Installing frontend dependencies..."
        cd frontend
        npm install
        cd ..
    fi
}

wait_for_service() {
    local url=$1
    local name=$2
    local max_attempts=${3:-30}
    local attempt=1

    log "Waiting for $name..."
    while [ $attempt -le $max_attempts ]; do
        if curl -s -f "$url" > /dev/null 2>&1; then
            success "$name is ready!"
            return 0
        fi
        sleep 2
        attempt=$((attempt + 1))
    done

    warn "$name did not become ready in time"
    return 1
}

# =============================================================================
# INFRASTRUCTURE (Docker)
# =============================================================================

start_infra() {
    header "Starting Infrastructure (Docker)"

    log "Starting databases, Keycloak, Gitea, and MCP servers..."
    $DOCKER_COMPOSE -f "$COMPOSE_FILE" --env-file .env up -d

    log "Waiting for services to be healthy..."

    # Wait for critical services
    wait_for_service "http://localhost:5533" "PostgreSQL" 30 || true
    wait_for_service "http://localhost:8180/health/ready" "Keycloak" 60 || true
    wait_for_service "http://localhost:3100/api/healthz" "Gitea" 30 || true
    wait_for_service "http://localhost:9001/health" "MCP Coding" 20 || true
    wait_for_service "http://localhost:9002/health" "MCP Docker" 20 || true

    success "Infrastructure is running!"
    echo ""
    echo "  PostgreSQL:  localhost:5533"
    echo "  Keycloak:    http://localhost:8180"
    echo "  Gitea:       http://localhost:3100"
    echo "  MCP Coding:  http://localhost:9001"
    echo "  MCP Docker:  http://localhost:9002"
    echo "  Adminer:     http://localhost:8081"
    echo ""
}

stop_infra() {
    header "Stopping Infrastructure"
    $DOCKER_COMPOSE -f "$COMPOSE_FILE" down
    success "Infrastructure stopped."
}

# =============================================================================
# BACKEND (Local with hot reload)
# =============================================================================

start_backend() {
    header "Starting Backend (Local with Hot Reload)"

    check_python
    setup_python_venv

    # Check if already running
    if [ -f "$BACKEND_PID_FILE" ] && kill -0 $(cat "$BACKEND_PID_FILE") 2>/dev/null; then
        warn "Backend already running (PID: $(cat $BACKEND_PID_FILE))"
        return 0
    fi

    # Create workspace directory if needed
    mkdir -p workspace

    # Set environment variables for local development
    export DATABASE_URL="postgresql://druppie:druppie_secret@localhost:5533/druppie"
    export DEV_MODE="${DEV_MODE:-false}"
    export KEYCLOAK_SERVER_URL="http://localhost:8180"
    export KEYCLOAK_ISSUER_URL="http://localhost:8180"
    export KEYCLOAK_REALM="druppie"
    export KEYCLOAK_CLIENT_ID="druppie-backend"
    export CORS_ORIGINS="http://localhost:5173,http://localhost:5273"
    export GITEA_URL="http://localhost:3100"
    export GITEA_INTERNAL_URL="http://localhost:3100"
    export GITEA_ADMIN_USER="gitea_admin"
    export GITEA_ADMIN_PASSWORD="GiteaAdmin123"
    export GITEA_ADMIN_EMAIL="admin@druppie.local"
    export GITEA_ORG="druppie"
    export WORKSPACE_PATH="$(pwd)/workspace"
    export INTERNAL_API_KEY="druppie-internal-secret-key"
    export USE_MCP_MICROSERVICES="true"
    export MCP_CODING_URL="http://localhost:9001"
    export MCP_DOCKER_URL="http://localhost:9002"
    export PYTHONPATH="$(pwd)"

    # Load API keys from .env if exists
    if [ -f ".env" ]; then
        set -a
        source .env
        set +a
    fi

    log "Starting uvicorn with --reload..."

    # Start backend in background
    source venv/bin/activate
    nohup uvicorn druppie.api.main:app \
        --host 0.0.0.0 \
        --port 8000 \
        --reload \
        --reload-dir druppie \
        > /tmp/druppie-backend.log 2>&1 &

    echo $! > "$BACKEND_PID_FILE"

    sleep 2

    if kill -0 $(cat "$BACKEND_PID_FILE") 2>/dev/null; then
        success "Backend started (PID: $(cat $BACKEND_PID_FILE))"
        echo ""
        echo "  Backend API: http://localhost:8000"
        echo "  API Docs:    http://localhost:8000/docs"
        echo "  Logs:        tail -f /tmp/druppie-backend.log"
        echo ""
    else
        error "Backend failed to start. Check /tmp/druppie-backend.log"
    fi
}

stop_backend() {
    header "Stopping Backend"

    if [ -f "$BACKEND_PID_FILE" ]; then
        PID=$(cat "$BACKEND_PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            kill "$PID"
            rm -f "$BACKEND_PID_FILE"
            success "Backend stopped (PID: $PID)"
        else
            rm -f "$BACKEND_PID_FILE"
            warn "Backend was not running"
        fi
    else
        warn "No backend PID file found"
    fi
}

# =============================================================================
# FRONTEND (Local with Vite HMR)
# =============================================================================

start_frontend() {
    header "Starting Frontend (Local with Vite HMR)"

    check_node
    setup_node_modules

    # Check if already running
    if [ -f "$FRONTEND_PID_FILE" ] && kill -0 $(cat "$FRONTEND_PID_FILE") 2>/dev/null; then
        warn "Frontend already running (PID: $(cat $FRONTEND_PID_FILE))"
        return 0
    fi

    cd frontend

    # Set environment variables
    export VITE_API_URL="http://localhost:8000"
    export VITE_KEYCLOAK_URL="http://localhost:8180"
    export VITE_KEYCLOAK_REALM="druppie"
    export VITE_KEYCLOAK_CLIENT_ID="druppie-frontend"

    log "Starting Vite dev server with HMR..."

    # Start frontend in background
    nohup npm run dev > /tmp/druppie-frontend.log 2>&1 &

    echo $! > "$FRONTEND_PID_FILE"

    cd ..

    sleep 3

    if kill -0 $(cat "$FRONTEND_PID_FILE") 2>/dev/null; then
        success "Frontend started (PID: $(cat $FRONTEND_PID_FILE))"
        echo ""
        echo "  Frontend:    http://localhost:5173"
        echo "  Logs:        tail -f /tmp/druppie-frontend.log"
        echo ""
    else
        error "Frontend failed to start. Check /tmp/druppie-frontend.log"
    fi
}

stop_frontend() {
    header "Stopping Frontend"

    if [ -f "$FRONTEND_PID_FILE" ]; then
        PID=$(cat "$FRONTEND_PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            kill "$PID"
            rm -f "$FRONTEND_PID_FILE"
            success "Frontend stopped (PID: $PID)"
        else
            rm -f "$FRONTEND_PID_FILE"
            warn "Frontend was not running"
        fi
    else
        warn "No frontend PID file found"
    fi
}

# =============================================================================
# KEYCLOAK SETUP
# =============================================================================

configure_keycloak() {
    header "Configuring Keycloak"

    if [ -f "scripts/setup_keycloak.py" ]; then
        source venv/bin/activate
        python scripts/setup_keycloak.py
        success "Keycloak configured!"
    else
        warn "Keycloak setup script not found"
    fi
}

configure_gitea() {
    header "Configuring Gitea"

    if [ -f "scripts/setup_gitea.py" ]; then
        source venv/bin/activate
        python scripts/setup_gitea.py
        success "Gitea configured!"
    else
        warn "Gitea setup script not found"
    fi
}

# =============================================================================
# STATUS & LOGS
# =============================================================================

show_status() {
    header "Service Status"

    echo "Infrastructure (Docker):"
    $DOCKER_COMPOSE -f "$COMPOSE_FILE" ps

    echo ""
    echo "Local Services:"

    if [ -f "$BACKEND_PID_FILE" ] && kill -0 $(cat "$BACKEND_PID_FILE") 2>/dev/null; then
        echo -e "  Backend:  ${GREEN}Running${NC} (PID: $(cat $BACKEND_PID_FILE))"
    else
        echo -e "  Backend:  ${RED}Stopped${NC}"
    fi

    if [ -f "$FRONTEND_PID_FILE" ] && kill -0 $(cat "$FRONTEND_PID_FILE") 2>/dev/null; then
        echo -e "  Frontend: ${GREEN}Running${NC} (PID: $(cat $FRONTEND_PID_FILE))"
    else
        echo -e "  Frontend: ${RED}Stopped${NC}"
    fi

    echo ""
    echo "URLs:"
    echo "  Frontend:    http://localhost:5173"
    echo "  Backend:     http://localhost:8000"
    echo "  API Docs:    http://localhost:8000/docs"
    echo "  Keycloak:    http://localhost:8180"
    echo "  Gitea:       http://localhost:3100"
    echo "  Adminer:     http://localhost:8081"
}

show_logs() {
    local service=${1:-}

    if [ -z "$service" ]; then
        header "Infrastructure Logs"
        $DOCKER_COMPOSE -f "$COMPOSE_FILE" logs -f --tail=100
    elif [ "$service" == "backend" ]; then
        header "Backend Logs"
        tail -f /tmp/druppie-backend.log
    elif [ "$service" == "frontend" ]; then
        header "Frontend Logs"
        tail -f /tmp/druppie-frontend.log
    else
        header "Logs for $service"
        $DOCKER_COMPOSE -f "$COMPOSE_FILE" logs -f --tail=100 "$service"
    fi
}

# =============================================================================
# MAIN
# =============================================================================

start_all() {
    header "Starting Druppie Development Environment"

    start_infra

    # Configure Keycloak and Gitea if first run
    if ! curl -s http://localhost:8180/realms/druppie > /dev/null 2>&1; then
        configure_keycloak
        configure_gitea
    fi

    start_backend
    start_frontend

    success "Development environment is ready!"
    echo ""
    echo "  Frontend:    http://localhost:5173"
    echo "  Backend:     http://localhost:8000"
    echo "  API Docs:    http://localhost:8000/docs"
    echo ""
    echo "Hot reload is enabled:"
    echo "  - Backend changes: Auto-reload via uvicorn"
    echo "  - Frontend changes: Instant via Vite HMR"
    echo ""
    echo "Useful commands:"
    echo "  ./setup_dev.sh status   - Show status"
    echo "  ./setup_dev.sh logs     - Show infra logs"
    echo "  ./setup_dev.sh logs backend  - Show backend logs"
    echo "  ./setup_dev.sh logs frontend - Show frontend logs"
    echo "  ./setup_dev.sh stop     - Stop everything"
}

stop_all() {
    stop_frontend
    stop_backend
    stop_infra
    success "All services stopped."
}

# =============================================================================
# COMMAND HANDLING
# =============================================================================

case "${1:-}" in
    infra)
        start_infra
        ;;
    backend)
        start_backend
        ;;
    frontend)
        start_frontend
        ;;
    stop)
        stop_all
        ;;
    stop-infra)
        stop_infra
        ;;
    stop-backend)
        stop_backend
        ;;
    stop-frontend)
        stop_frontend
        ;;
    restart)
        stop_all
        start_all
        ;;
    restart-backend)
        stop_backend
        start_backend
        ;;
    restart-frontend)
        stop_frontend
        start_frontend
        ;;
    status)
        show_status
        ;;
    logs)
        show_logs "${2:-}"
        ;;
    configure)
        configure_keycloak
        configure_gitea
        ;;
    ""|start)
        start_all
        ;;
    *)
        echo "Usage: $0 {start|infra|backend|frontend|stop|restart|status|logs|configure}"
        echo ""
        echo "Commands:"
        echo "  start         Start everything (default)"
        echo "  infra         Start only infrastructure (Docker)"
        echo "  backend       Start only backend (local)"
        echo "  frontend      Start only frontend (local)"
        echo "  stop          Stop everything"
        echo "  stop-infra    Stop only infrastructure"
        echo "  stop-backend  Stop only backend"
        echo "  stop-frontend Stop only frontend"
        echo "  restart       Restart everything"
        echo "  restart-backend   Restart backend only"
        echo "  restart-frontend  Restart frontend only"
        echo "  status        Show service status"
        echo "  logs [svc]    Show logs (infra, backend, or frontend)"
        echo "  configure     Run Keycloak & Gitea configuration"
        exit 1
        ;;
esac

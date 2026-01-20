#!/bin/bash
# =============================================================================
# Druppie E2E Test Runner
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${YELLOW}[TEST]${NC} $1"; }
success() { echo -e "${GREEN}[PASS]${NC} $1"; }
error() { echo -e "${RED}[FAIL]${NC} $1"; }

# Check if services are running
check_services() {
    log "Checking if services are running..."

    # Check Keycloak
    if ! curl -sf http://localhost:8080/health/ready >/dev/null 2>&1; then
        error "Keycloak is not running"
        return 1
    fi
    success "Keycloak is up"

    # Check Backend
    if ! curl -sf http://localhost:8000/health >/dev/null 2>&1; then
        error "Backend is not running"
        return 1
    fi
    success "Backend is up"

    # Check Frontend
    if ! curl -sf http://localhost:5173 >/dev/null 2>&1; then
        error "Frontend is not running"
        return 1
    fi
    success "Frontend is up"

    return 0
}

# Run backend tests
run_backend_tests() {
    log "Running backend tests..."
    cd "$PROJECT_DIR/backend"

    if [ -f requirements.txt ]; then
        pip install -q pytest pytest-asyncio httpx
    fi

    python -m pytest tests/ -v --tb=short 2>&1 || true

    cd "$PROJECT_DIR"
}

# Run E2E tests
run_e2e_tests() {
    log "Running E2E tests with Playwright..."
    cd "$PROJECT_DIR/frontend"

    # Install Playwright browsers if needed
    npx playwright install chromium --with-deps 2>/dev/null || true

    # Run tests
    npx playwright test --reporter=list

    cd "$PROJECT_DIR"
}

# Main
main() {
    echo "============================================================="
    echo "Druppie Governance Platform - E2E Test Suite"
    echo "============================================================="
    echo ""

    # Check services
    if ! check_services; then
        echo ""
        error "Services not running. Start with: ./setup.sh start"
        exit 1
    fi

    echo ""

    # Run tests based on argument
    case "${1:-all}" in
        backend)
            run_backend_tests
            ;;
        e2e)
            run_e2e_tests
            ;;
        all)
            run_backend_tests
            echo ""
            run_e2e_tests
            ;;
        *)
            echo "Usage: $0 {all|backend|e2e}"
            exit 1
            ;;
    esac

    echo ""
    echo "============================================================="
    success "Test run completed!"
    echo "============================================================="
}

main "$@"

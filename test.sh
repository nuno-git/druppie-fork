#!/bin/bash
# =============================================================================
# Druppie Test Runner - Runs all test suites
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"

cd "$PROJECT_DIR"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${BLUE}[TEST]${NC} $1"; }
success() { echo -e "${GREEN}[PASS]${NC} $1"; }
error() { echo -e "${RED}[FAIL]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

# Check if Python is available
check_python() {
    if ! command -v python &> /dev/null; then
        error "Python not found. Please install Python 3.11+"
        return 1
    fi
    
    local python_version=$(python --version 2>&1 | awk '{print $2}')
    log "Python version: $python_version"
    success "Python found"
}

# Check if Node.js is available
check_node() {
    if ! command -v node &> /dev/null; then
        error "Node.js not found. Please install Node.js"
        return 1
    fi
    
    local node_version=$(node --version)
    log "Node version: $node_version"
    success "Node.js found"
}

# Check Docker if needed
check_docker() {
    if [ "$TEST_TYPE" == "e2e" ] || [ "$TEST_TYPE" == "all" ]; then
        if ! command -v docker &> /dev/null; then
            warn "Docker not found. E2E tests may not work without running services."
            return 1
        fi
        
        if ! docker info &> /dev/null; then
            warn "Docker daemon not running. Services may not be available."
            return 1
        fi
        success "Docker is running"
    fi
}

# Check Python dependencies
check_python_deps() {
    log "Checking Python dependencies..."
    local missing=0
    
    python -c "import pytest" 2>/dev/null || {
        error "pytest not installed. Run: pip install pytest"
        missing=1
    }
    
    python -c "import pytest_asyncio" 2>/dev/null || {
        error "pytest-asyncio not installed. Run: pip install pytest-asyncio"
        missing=1
    }
    
    python -c "import pytest_cov" 2>/dev/null || {
        warn "pytest-cov not installed. Coverage reports won't work. Run: pip install pytest-cov"
    }
    
    python -c "import httpx" 2>/dev/null || {
        error "httpx not installed. Run: pip install httpx"
        missing=1
    }
    
    if [ $missing -eq 0 ]; then
        success "All Python dependencies installed"
    else
        return 1
    fi
}

# Check Node.js dependencies
check_node_deps() {
    log "Checking Node.js dependencies..."
    local missing=0
    
    cd "$PROJECT_DIR/frontend"
    
    if [ ! -f "package.json" ]; then
        error "package.json not found in frontend/"
        return 1
    fi
    
    if ! command -v npm &> /dev/null; then
        error "npm not found. Please install Node.js"
        return 1
    fi
    
    # Check if node_modules exists
    if [ ! -d "node_modules" ]; then
        error "node_modules not found. Run: npm install"
        return 1
    fi
    
    # Check vitest
    if ! npm list vitest --depth=0 &> /dev/null; then
        error "vitest not installed. Run: npm install"
        missing=1
    fi
    
    # Check @vitest/coverage-v8
    if ! npm list "@vitest/coverage-v8" --depth=0 &> /dev/null; then
        warn "@vitest/coverage-v8 not installed. Coverage reports won't work. Run: npm install --save-dev @vitest/coverage-v8"
    fi
    
    # Check playwright
    if ! npm list "@playwright/test" --depth=0 &> /dev/null; then
        error "@playwright/test not installed. Run: npm install"
        missing=1
    fi
    
    cd "$PROJECT_DIR"
    
    if [ $missing -eq 0 ]; then
        success "All Node.js dependencies installed"
    else
        return 1
    fi
}

# Check if services are running (for E2E tests)
check_services() {
    if [ "$TEST_TYPE" == "e2e" ] || [ "$TEST_TYPE" == "all" ]; then
        log "Checking if services are running..."
        local running=0
        
        if curl -sf http://localhost:8180/health/ready >/dev/null 2>&1; then
            success "Keycloak is running (http://localhost:8180)"
            running=$((running + 1))
        else
            warn "Keycloak is not running"
        fi
        
        if curl -sf http://localhost:8100/health >/dev/null 2>&1; then
            success "Backend is running (http://localhost:8100)"
            running=$((running + 1))
        else
            warn "Backend is not running"
        fi
        
        if curl -sf http://localhost:5273 >/dev/null 2>&1; then
            success "Frontend is running (http://localhost:5273)"
            running=$((running + 1))
        else
            warn "Frontend is not running"
        fi
        
        if [ $running -lt 3 ]; then
            warn "Some services are not running. Start with: ./setup.sh start"
            warn "E2E tests may fail without running services."
        fi
    fi
}

# Install missing dependencies
install_deps() {
    log "Installing missing dependencies..."
    
    cd "$PROJECT_DIR/druppie"
    if [ -f "requirements.txt" ]; then
        log "Installing Python dependencies..."
        python -m pip install -q -r requirements.txt || {
            error "Failed to install Python dependencies"
            return 1
        }
        success "Python dependencies installed"
    fi
    
    cd "$PROJECT_DIR/frontend"
    if [ -f "package.json" ]; then
        log "Installing Node.js dependencies..."
        npm install --silent || {
            error "Failed to install Node.js dependencies"
            return 1
        }
        success "Node.js dependencies installed"
    fi
    
    cd "$PROJECT_DIR"
}

# Run TDD workflow tests
run_tdd_tests() {
    log "Running TDD workflow tests..."
    export TEST_TYPE="tdd"
    
    # Set PYTHONPATH to include project directory
    export PYTHONPATH="$PROJECT_DIR:$PYTHONPATH"
    
    if [ -f "$PROJECT_DIR/tests/test_tdd_workflow.py" ]; then
        cd "$PROJECT_DIR/tests"
        python test_tdd_workflow.py || {
            cd "$PROJECT_DIR"
            error "TDD workflow tests failed"
            return 1
        }
        cd "$PROJECT_DIR"
        success "TDD workflow tests passed"
    else
        warn "TDD workflow test file not found, skipping"
    fi
}

# Run backend tests
run_backend_tests() {
    log "Running backend tests..."
    export TEST_TYPE="backend"
    cd "$PROJECT_DIR/druppie"
    
    if [ ! -d "tests" ]; then
        warn "No backend tests directory found, skipping"
        cd "$PROJECT_DIR"
        return 0
    fi
    
    python -m pytest tests/ -v --tb=short 2>&1 || {
        error "Backend tests failed"
        cd "$PROJECT_DIR"
        return 1
    }
    success "Backend tests passed"
    cd "$PROJECT_DIR"
}

# Run frontend unit tests
run_frontend_unit_tests() {
    log "Running frontend unit tests..."
    export TEST_TYPE="frontend"
    cd "$PROJECT_DIR/frontend"
    
    if [ -f "package.json" ]; then
        if grep -q '"vitest"' package.json; then
            npm run test -- --run || {
                error "Frontend unit tests failed"
                cd "$PROJECT_DIR"
                return 1
            }
            success "Frontend unit tests passed"
        else
            warn "Vitest not configured in package.json, skipping unit tests"
        fi
    else
        warn "package.json not found, skipping frontend unit tests"
    fi
    
    cd "$PROJECT_DIR"
}

# Run E2E tests
run_e2e_tests() {
    log "Running E2E tests with Playwright..."
    export TEST_TYPE="e2e"
    cd "$PROJECT_DIR/frontend"
    
    # Check if services are running
    log "Checking if services are running..."
    
    if ! curl -sf http://localhost:8180/health/ready >/dev/null 2>&1; then
        warn "Keycloak is not running. Start with: ./setup.sh start"
    fi
    
    if ! curl -sf http://localhost:8100/health >/dev/null 2>&1; then
        warn "Backend is not running. Start with: ./setup.sh start"
    fi
    
    if ! curl -sf http://localhost:5273 >/dev/null 2>&1; then
        warn "Frontend is not running. Start with: ./setup.sh start"
    fi
    
    # Install Playwright browsers if needed
    log "Ensuring Playwright browsers are installed..."
    npx playwright install chromium --with-deps 2>/dev/null || true
    
    # Run tests
    if [ -f "playwright.config.js" ]; then
        npm run test:e2e || {
            error "E2E tests failed"
            cd "$PROJECT_DIR"
            return 1
        }
        success "E2E tests passed"
    else
        warn "Playwright config not found, skipping E2E tests"
    fi
    
    cd "$PROJECT_DIR"
}

# Main
main() {
    echo "============================================================="
    echo "Druppie Governance Platform - Complete Test Suite"
    echo "============================================================="
    echo ""
    
    # Check requirements
    log "Checking system requirements..."
    check_python || exit 1
    check_node || exit 1
    check_docker
    echo ""
    
    # Check dependencies
    check_python_deps || {
        warn "Some Python dependencies missing"
        log "Run: ./test.sh install to install missing dependencies"
        exit 1
    }
    check_node_deps || {
        warn "Some Node.js dependencies missing"
        log "Run: ./test.sh install to install missing dependencies"
        exit 1
    }
    echo ""
    
    # Check services
    check_services
    echo ""
    
    # Check for install command first
    if [ "$1" == "install" ]; then
        install_deps
        exit 0
    fi
    
    # Run tests based on argument
    case "${1:-all}" in
        tdd)
            run_tdd_tests
            ;;
        backend)
            run_backend_tests
            ;;
        frontend)
            run_frontend_unit_tests
            ;;
        e2e)
            run_e2e_tests
            ;;
        unit)
            run_tdd_tests
            echo ""
            run_backend_tests
            echo ""
            run_frontend_unit_tests
            ;;
        all)
            run_tdd_tests
            echo ""
            run_backend_tests
            echo ""
            run_frontend_unit_tests
            echo ""
            run_e2e_tests
            ;;
        *)
            echo "Usage: $0 {all|tdd|backend|frontend|e2e|unit|install}"
            echo ""
            echo "Commands:"
            echo "  all      - Run all tests (default)"
            echo "  tdd      - Run TDD workflow tests only"
            echo "  backend   - Run backend pytest tests only"
            echo "  frontend - Run frontend vitest unit tests only"
            echo "  e2e      - Run Playwright E2E tests only"
            echo "  unit     - Run all unit tests (tdd + backend + frontend)"
            echo "  install  - Install all dependencies (Python + Node.js)"
            echo ""
            echo "Examples:"
            echo "  ./test.sh install   # Install all dependencies"
            echo "  ./test.sh tdd       # Run only TDD tests"
            echo "  ./test.sh all       # Run everything"
            exit 1
            ;;
    esac
    
    echo ""
    echo "============================================================="
    success "All requested tests passed!"
    echo "============================================================="
}

main "$@"

#!/bin/bash
# =============================================================================
# Virtual Environment Setup Script for Druppie (Linux/Mac)
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[PASS]${NC} $1"; }
error() { echo -e "${RED}[FAIL]${NC} $1"; exit 1; }

echo "============================================================="
echo "Setting up Python virtual environment for Druppie"
echo "============================================================="
echo ""

# Check if venv exists
if [ -d "venv" ]; then
    log "Virtual environment already exists"
    read -p "Recreate? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        log "Removing existing venv..."
        rm -rf venv
    else
        log "Using existing venv"
    fi
fi

# Create venv if it doesn't exist
if [ ! -d "venv" ]; then
    log "Creating virtual environment..."
    python -m venv venv || error "Failed to create virtual environment"
    success "Virtual environment created"
fi

echo ""
echo "============================================================="
echo "Activating virtual environment..."
echo "============================================================="

if [ -f "venv/Scripts/activate" ]; then
    source venv/Scripts/activate
elif [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
else
    error "Virtual environment activation script not found"
fi

echo ""
echo "============================================================="
echo "Installing Python dependencies..."
echo "============================================================="

# Upgrade pip
log "Upgrading pip..."
pip install --quiet --upgrade pip

# Install all requirements
if [ -f "druppie/requirements.txt" ]; then
    log "Installing from druppie/requirements.txt"
    pip install -r druppie/requirements.txt || error "Failed to install druppie/requirements.txt"
fi

if [ -f "requirements.txt" ]; then
    log "Installing from requirements.txt"
    pip install -r requirements.txt || error "Failed to install requirements.txt"
fi

if [ ! -f "druppie/requirements.txt" ] && [ ! -f "requirements.txt" ]; then
    error "No requirements.txt found"
fi

success "All dependencies installed"

echo ""
echo "============================================================="
echo "[PASS] Virtual environment setup complete!"
echo "============================================================="
echo ""
echo "To activate the virtual environment:"
if [ -f "venv/Scripts/activate" ]; then
    echo "  source venv/Scripts/activate"
else
    echo "  source venv/bin/activate"
fi
echo ""
echo "To deactivate:"
echo "  deactivate"
echo ""
echo "Development commands:"
echo "  python --version"
echo "  pytest --version"
echo ""

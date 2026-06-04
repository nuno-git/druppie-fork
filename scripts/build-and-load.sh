#!/usr/bin/env bash
set -euo pipefail

# Build Druppie Docker images and load them into kind cluster
# Usage: ./scripts/build-and-load.sh [image-name]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CLUSTER_NAME="druppie"
SOURCE_DIR="$PROJECT_DIR"

# Colors
GREEN='\033[0;32m'
NC='\033[0m'
log() { echo -e "${GREEN}[druppie]${NC} $*"; }

build_and_load() {
    local image_name="$1"
    local dockerfile="$2"
    local context="$3"

    log "Building $image_name..."
    docker build -t "$image_name:latest" -f "$dockerfile" "$context"

    log "Loading $image_name into kind..."
    kind load docker-image "$image_name:latest" --name "$CLUSTER_NAME"
}

# Build all images
build_all() {
    log "Building all Druppie images..."

    # Backend
    build_and_load "druppie-backend" "$SOURCE_DIR/Dockerfile" "$SOURCE_DIR"

    # Frontend
    build_and_load "druppie-frontend" "$SOURCE_DIR/frontend/Dockerfile" "$SOURCE_DIR/frontend"

    # Init
    build_and_load "druppie-init" "$SOURCE_DIR/Dockerfile.init" "$SOURCE_DIR"

    # MCP Modules - build from mcp-servers context
    local MCP_DIR="$SOURCE_DIR/druppie/mcp-servers"
    for module in coding docker filesearch web archimate registry llm vision; do
        if [ -f "$MCP_DIR/module-$module/Dockerfile" ]; then
            build_and_load "druppie-module-$module" "$MCP_DIR/module-$module/Dockerfile" "$MCP_DIR"
        fi
    done

    # Sandbox image
    if [ -f "$MCP_DIR/module-coding/Dockerfile.sandbox" ]; then
        build_and_load "druppie-sandbox" "$MCP_DIR/module-coding/Dockerfile.sandbox" "$MCP_DIR"
    fi

    log "All images built and loaded!"
}

case "${1:-all}" in
    backend)
        build_and_load "druppie-backend" "$SOURCE_DIR/Dockerfile" "$SOURCE_DIR"
        ;;
    frontend)
        build_and_load "druppie-frontend" "$SOURCE_DIR/frontend/Dockerfile" "$SOURCE_DIR/frontend"
        ;;
    module-*)
        module="${1#module-}"
        build_and_load "druppie-module-$module" "$SOURCE_DIR/druppie/mcp-servers/module-$module/Dockerfile" "$SOURCE_DIR/druppie/mcp-servers"
        ;;
    all)
        build_all
        ;;
    *)
        echo "Usage: $0 {all|backend|frontend|module-<name>}"
        echo "  Modules: coding, docker, filesearch, web, archimate, registry, llm, vision"
        exit 1
        ;;
esac

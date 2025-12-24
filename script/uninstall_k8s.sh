#!/bin/bash

# Druppie Uninstaller
# Removes RKE2 or k3d clusters

set -e

COLOR_RED='\033[0;31m'
COLOR_NC='\033[0m'

# Log File Location (Project Root)
LOG_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../.druppie_history"

function log() {
    echo -e "${COLOR_RED}[UNINSTALL]${COLOR_NC} $1"
}

function log_history() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') | UNINSTALL | Kubernetes | $1" >> "$LOG_FILE"
}

echo "Which Kubernetes distribution do you want to remove?"
echo "1) k3d (Docker Container)"
echo "2) RKE2 (Linux Service)"

if [ -n "$1" ]; then
    case $1 in
        1|k3d) OPT="1" ;;
        2|rke2) OPT="2" ;;
        *) echo "Invalid argument: $1"; exit 1 ;;
    esac
    echo "Selected Option: $1 ($OPT)"
else
    read -p "Choice [1-2]: " OPT
fi

if [ "$OPT" == "2" ]; then
    # RKE2 Uninstall
    if [[ $EUID -ne 0 ]]; then
       echo "RKE2 uninstall requires root."
       exit 1
    fi
    
    log "Stopping RKE2..."
    systemctl stop rke2-server
    systemctl disable rke2-server
    
    log "Running RKE2 Uninstall Script..."
    if [ -f /usr/local/bin/rke2-uninstall.sh ]; then
        /usr/local/bin/rke2-uninstall.sh
    else
        echo "Uninstall script not found. Was RKE2 installed?"
        exit 1
    fi
    
    log "RKE2 removed."
    log_history "RKE2"

elif [ "$OPT" == "1" ]; then
    # k3d Uninstall
    CLUSTER_NAME="${DRUPPIE_CLUSTER_NAME:-druppie-dev}"
    log "Deleting '$CLUSTER_NAME' cluster..."
    if command -v k3d &> /dev/null; then
        k3d cluster delete "$CLUSTER_NAME"
        log "Cluster deleted."
        log_history "k3d ($CLUSTER_NAME)"
        if [[ "$(uname)" == "Darwin" ]]; then
            # macOS: Remove k3d binary
            brew uninstall k3d
            log "k3d removed."
            log_history "k3d"
        else
            # Linux: Remove k3d binary
            sudo rm -f /usr/local/bin/k3d
            log "k3d removed."
            log_history "k3d"
        fi
    else
        echo "k3d binary not found."
    fi

else
    echo "Invalid choice."
fi

#!/bin/bash

# Druppie Master CLI
# Interface voor alle beheer taken binnen het Druppie Platform.

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_DIR="$BASE_DIR/script"

COLOR_CYAN='\033[0;36m'
COLOR_NC='\033[0m'
SECRETS_FILE="$BASE_DIR/.secrets"

function load_secrets() {
    if [ ! -f "$SECRETS_FILE" ]; then
        touch "$SECRETS_FILE"
    fi
    source "$SECRETS_FILE"
}

function get_or_create_secret() {
    local key=$1
    local existing_value=${!key}

    if [ -z "$existing_value" ]; then
        # Generate a random 16-char secret
        local new_secret=$(openssl rand -hex 8)
        echo "$key=$new_secret" >> "$SECRETS_FILE"
        export $key=$new_secret
    else
        export $key=$existing_value
    fi
}

function ensure_secrets() {
    # Define required secrets for each installer
    get_or_create_secret "DRUPPIE_K8S_TOKEN"       # k8s
    get_or_create_secret "DRUPPIE_RANCHER_TOKEN"   # Rancher
    get_or_create_secret "DRUPPIE_GITEA_PASS"      # data
    get_or_create_secret "DRUPPIE_MINIO_PASS"      # data
    get_or_create_secret "DRUPPIE_SONAR_PASS"      # security
    get_or_create_secret "DRUPPIE_KEYCLOAK_PASS"   # iam
    get_or_create_secret "DRUPPIE_GRAFANA_PASS"    # observability
    get_or_create_secret "DRUPPIE_POSTGRES_PASS"   # database
    get_or_create_secret "DRUPPIE_QDRANT_KEY"      # database
    get_or_create_secret "DRUPPIE_GEOSERVER_PASS"  # gis
    get_or_create_secret "DRUPPIE_MONITOR_PASS"    # security
    
    # Reload to be sure
    source "$SECRETS_FILE"
}

function show_banner() {
    clear
    echo -e "${COLOR_CYAN}"
    echo "  _____                        _      "
    echo " |  __ \                      (_)     "
    echo " | |  | |_ __ _   _ _ __  _ __ _  ___ "
    echo " | |  | | '__| | | | '_ \| '_ \ |/ _ \\"
    echo " | |__| | |  | |_| | |_) | |_) | |  __/"
    echo " |_____/|_|   \__,_| .__/| .__/|_|\___|"
    echo "                   | |   | |          "
    echo "                   |_|   |_|          "
    echo -e "${COLOR_NC}"
    echo " v1.0 - Platform CLI"
    echo ""
}

function menu() {
    show_banner
    echo "Beschikbare Acties:"
    echo "-------------------"
    echo "1) ☸️  Install Kubernetes (RKE2/k3d)"
    echo "2) 🚀 Bootstrap DEV Platform (Helm + Flux CD + Kyverno + Tekton + Kong + Postgres)"
    echo "3) 💾 Install Data Services (Gitea + MinIO + Qdrant)"
    echo "4) 🛡️  Install Security Services (Trivy + SonarQube)"
    echo "5) 🔑 Install IAM (Keycloak)"
    echo "6) 👁️  Install Observability (LGTM Stack)"
    echo "7) 🌍 Install GIS Services (GeoServer + GEONode + WebODM)"
    echo "8) 🤠 Install Rancher UI (Cert-Manager + Rancher)"
    echo ""
    echo "a) ⏩ Install EVERYTHING (1-8)"
    echo "u) 🗑️  Uninstall Kubernetes"
    echo "h) 📜 List Installation History"
    echo "q) Quit"
    echo ""
    read -p "Maak een keuze: " CHOICE
    execute_choice "$CHOICE"
}


# Global flag to track if we are running in interactive mode
INTERACTIVE_MODE=true

function handle_wait() {
    local exit_code=$?
    # Wait if the last command failed OR if we are in interactive mode and just finished a menu action
    if [ $exit_code -ne 0 ] || [ "$INTERACTIVE_MODE" = true ]; then
        # If it failed, show why we are waiting
        if [ $exit_code -ne 0 ]; then
             echo "⚠️  Command failed with exit code $exit_code."
        fi
        read -p "Druk op Enter..."
    fi
}


function execute_choice() {
    local choice=$1
    case $choice in
        1) handle_k8s_install
            handle_wait
            ;;
        2) install_platform
            handle_wait
            ;;
        3) install_data
            handle_wait
            ;;
        4) install_security
            handle_wait
            ;;
        5) install_iam
            handle_wait
            ;;
        6) install_observability
            handle_wait
            ;;
        7) install_gis
            handle_wait
            ;;
        8) install_rancher
            handle_wait
            ;;
        a)
            handle_k8s_install
            install_platform
            install_data
            install_security
            install_iam
            install_observability
            install_gis
            install_rancher
            handle_wait
            ;;
        u) handle_uninstall
            handle_wait
            ;;
        h) show_history
            handle_wait
            ;;
        q) echo "Bye!"; exit 0 ;;
        *) echo "Ongeldige keuze: $choice" ;;
    esac
}

function handle_k8s_install() {
    if [[ "$(uname)" == "Darwin" ]]; then
        # macOS: Run directly (likely k3d)
        bash "$SCRIPT_DIR/install_k8s.sh"
    else
        sudo bash "$SCRIPT_DIR/install_k8s.sh"
    fi
}

function handle_uninstall() {
    echo ""
    echo "Uninstalling Kubernetes Cluster..."
    if [[ "$(uname)" == "Darwin" ]]; then
        # macOS: Run directly (likely k3d)
        bash "$SCRIPT_DIR/uninstall_k8s.sh"
    else
        # Linux: Needs sudo
        sudo bash "$SCRIPT_DIR/uninstall_k8s.sh"
    fi
}

function install_platform() {
    echo "Bootstrapping Platform..."
    bash "$SCRIPT_DIR/setup_dev_env.sh"
}

function install_data() {
    echo "Installing Data Services..."
    bash "$SCRIPT_DIR/setup_data_tools.sh"
}

function install_security() {
    echo "Installing Security Services..."
    bash "$SCRIPT_DIR/setup_security_tools.sh"
}

function install_iam() {
    echo "Installing IAM Services..."
    bash "$SCRIPT_DIR/setup_iam.sh"
}

function install_observability() {
    echo "Installing Observability Stack..."
    bash "$SCRIPT_DIR/setup_observability.sh"
}

function install_gis() {
    echo "Installing GIS Services..."
    bash "$SCRIPT_DIR/setup_gis.sh"
}

function install_rancher() {
    echo "Installing Rancher UI..."
    bash "$SCRIPT_DIR/setup_rancher.sh"
}

function show_history() {
    echo ""
    echo "Installation History:"
    echo "---------------------"
    if [ -f "$BASE_DIR/.druppie_history" ]; then
        cat "$BASE_DIR/.druppie_history"
    else
        echo "No history found."
    fi
    echo ""
}

function handle_args() {
    for arg in "$@"; do
        execute_choice "$arg"
    done
}

# Start
load_secrets
ensure_secrets

if [ $# -gt 0 ]; then
    INTERACTIVE_MODE=false
    handle_args "$@"
else
    while true; do
        menu
    done
fi

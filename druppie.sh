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
    echo "2) 🚀 Bootstrap Platform (Base Layer)"
    echo "3) 💾 Install Data Services (Gitea + MinIO + Qdrant)"
    echo "4) 🛡️  Install Security Services (Trivy + SonarQube)"
    echo "5) 🔑 Install IAM (Keycloak)"
    echo "6) 👁️  Install Observability (LGTM Stack)"
    echo "7) 🌍 Install GIS Services (GeoServer + WebODM)"
    echo ""
    echo "u) 🗑️  Uninstall Kubernetes"
    echo "h) 📜 List Installation History"
    echo "q) Quit"
    echo ""
    read -p "Maak een keuze: " CHOICE

    case $CHOICE in
        1)
            handle_k8s_install
            ;;
        2)
            echo "Bootstrapping Platform..."
            bash "$SCRIPT_DIR/setup_dev_env.sh"
            read -p "Druk op Enter..."
            menu
            ;;
        3)
            echo "Installing Data Services..."
            bash "$SCRIPT_DIR/setup_data_tools.sh"
            read -p "Druk op Enter..."
            menu
            ;;
        4)
            echo "Installing Security Services..."
            bash "$SCRIPT_DIR/setup_security_tools.sh"
            read -p "Druk op Enter..."
            menu
            ;;
        5)
            echo "Installing IAM Services..."
            bash "$SCRIPT_DIR/setup_iam.sh"
            read -p "Druk op Enter..."
            menu
            ;;
        6)
            echo "Installing Observability Stack..."
            bash "$SCRIPT_DIR/setup_observability.sh"
            read -p "Druk op Enter..."
            menu
            ;;

        7)
            echo "Installing GIS Services..."
            bash "$SCRIPT_DIR/setup_gis.sh"
            read -p "Druk op Enter..."
            menu
            ;;

        u)
            handle_uninstall
            ;;
        h)
            echo ""
            echo "Installation History:"
            echo "---------------------"
            if [ -f "$BASE_DIR/.druppie_history" ]; then
                cat "$BASE_DIR/.druppie_history"
            else
                echo "No history found."
            fi
            echo ""
            read -p "Druk op Enter..."
            menu
            ;;
        q)
            echo "Bye!"
            exit 0
            ;;
        *)
            echo "Ongeldige keuze."
            sleep 1
            menu
            ;;
    esac
}

function handle_k8s_install() {
    if [[ "$(uname)" == "Darwin" ]]; then
        # macOS: Run directly (likely k3d)
        bash "$SCRIPT_DIR/install_k8s.sh"
    else
        sudo bash "$SCRIPT_DIR/install_k8s.sh"
    fi
    menu
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
    read -p "Druk op Enter..."
    menu
}

# Start
load_secrets
ensure_secrets
menu

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
    get_or_create_secret "DRUPPIE_GEOSERVER_PASS"  # gis
    get_or_create_secret "DRUPPIE_MONITOR_PASS"    # security

    # Ensure Domain
    if [ -z "${DRUPPIE_DOMAIN}" ]; then
        echo "DRUPPIE_DOMAIN=localhost" >> "$SECRETS_FILE"
        export DRUPPIE_DOMAIN="localhost"
    fi
    # Re-export to be safe
    export DRUPPIE_DOMAIN="${DRUPPIE_DOMAIN:-localhost}"

    # Ensure Cluster Name
    if [ -z "${DRUPPIE_CLUSTER_NAME}" ]; then
        echo "DRUPPIE_CLUSTER_NAME=druppie-dev" >> "$SECRETS_FILE"
        export DRUPPIE_CLUSTER_NAME="druppie-dev"
    fi
    export DRUPPIE_CLUSTER_NAME="${DRUPPIE_CLUSTER_NAME:-druppie-dev}"
    
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
    echo " 0) ☸️  Install Kubernetes (RKE2/k3d)"
    echo " 1) 🚀 Bootstrap DEV Platform (Helm + Flux CD + Kyverno + Tekton + Kong + Postgres)"
    echo " 2) 💾 Install Data Services (Gitea + MinIO + Qdrant)"
    echo " 3) 🛡️  Install Security Services (Trivy + SonarQube)"
    echo " 4) 🔑 Install IAM (Keycloak)"
    echo " 5) 👁️  Install Observability (LGTM Stack)"
    echo " 6) 🌍 Install GIS Services (GeoServer + GEONode + WebODM)"
    echo " 7) 🤠 Install Rancher UI (Cert-Manager + Rancher)"
    echo " 8) 💧 Build & Install Druppie"
    echo " 9) 🌐 Configure Ingress (Expose Services)"

    echo ""
    echo " a) ⏩ Install EVERYTHING (0-9)"
    echo " u) 🗑️  Uninstall Kubernetes"
    echo " h) 📜 List Installation History"
    echo " q) Quit"
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
    local extra_arg=$2
    case $choice in
        0) handle_k8s_install
            handle_wait
            ;;
        1) install_platform
            handle_wait
            ;;
        2) install_data
            handle_wait
            ;;
        3) install_security
            handle_wait
            ;;
        4) install_iam
            handle_wait
            ;;
        5) install_observability
            handle_wait
            ;;
        6) install_gis
            handle_wait
            ;;
        7) install_rancher
            handle_wait
            ;;
        8) install_druppie_core
            handle_wait
            ;;
        9) install_ingress
            handle_wait
            ;;

        a)
            handle_k8s_install || return 1
            install_platform || return 1
            install_data || return 1
            install_security || return 1
            install_iam || return 1
            install_observability || return 1
            install_gis || return 1
            install_rancher || return 1
            install_druppie || return 1
            install_ingress || return 1
            handle_wait
            ;;
        u) handle_uninstall "$extra_arg"
            handle_wait
            ;;
        ua)
            handle_uninstall "$extra_arg" || return 1
            execute_choice "a"
            ;;
        h) show_history
            handle_wait
            ;;
        q) echo "Bye!"; exit 0 ;;
        *) echo "Ongeldige keuze: $choice" ;;
    esac
}

LOG_DIR="$BASE_DIR/.logs"

# Function to run a script with logging
function run_script_logged() {
    local label=$1
    local script_path=$2
    # Capture remaining args
    shift 2
    local args="$@"
    
    local script_name=$(basename "$script_path")
    local log_file="$LOG_DIR/${script_name%.*}.log"

    # Ensure log directory exists
    mkdir -p "$LOG_DIR"
    
    # Empty the log file
    > "$log_file"
    
    # Execute with logging (both stdout and stderr to screen and file)
    # Wrap everything in a block to capture header echoes too
    {
        set -o pipefail
        echo "=================================================="
        echo " RUNNING: $label"
        echo " DATE:    $(date)"
        echo " SCRIPT:  $script_path"
        echo " LOG:     $log_file"
        echo "=================================================="
        echo ""
        
    # Run script with arguments
    if [ -n "$args" ]; then
        bash "$script_path" $args
    else
        bash "$script_path"
    fi
        
        EXIT_CODE=$?
        echo ""
        echo "=================================================="
        if [ $EXIT_CODE -eq 0 ]; then
            echo " STATUS:  SUCCESS ✅"
        else
            echo " STATUS:  FAILED ❌ (Exit Code: $EXIT_CODE)"
        fi
        echo "=================================================="
        set +o pipefail
        return $EXIT_CODE
    } 2>&1 | tee -a "$log_file"
    
    # Return the exit code of the pipeline (which is the exit code of the script due to pipefail)
    return ${PIPESTATUS[0]} 
}

function handle_k8s_install() {
    if [[ "$(uname)" == "Darwin" ]]; then
        # macOS: Run directly (likely k3d) -> Pass '1' to select k3d automatically
        run_script_logged "Kubernetes (k3d)" "$SCRIPT_DIR/install_k8s.sh" 1
    else
        # Linux: Could be 2 or 3. Let's default to 2 (Workstation) for 'druppie' default?
        # Or leave empty to prompt?
        # If running via 'druppie.sh i', user might expect interaction.
        # But logging wrapper might hide input? No, standard input is inherited usually.
        # However, run_script_logged pipes output to tee. Pipe behavior with input is tricky.
        # It's safer to pass arguments to avoid interaction inside a piped block.
        run_script_logged "Kubernetes (RKE2/k3s)" "$SCRIPT_DIR/install_k8s.sh" 2
    fi
}

function handle_uninstall() {
    local opt_arg=$1
    echo ""
    echo "Uninstalling Kubernetes Cluster..."
    if [[ "$(uname)" == "Darwin" ]]; then
        # macOS: Run directly
        run_script_logged "Uninstall Kubernetes" "$SCRIPT_DIR/uninstall_k8s.sh" $opt_arg
    else
        # Linux: Needs sudo
        run_script_logged "Uninstall Kubernetes" "$SCRIPT_DIR/uninstall_k8s.sh" $opt_arg
    fi
}

function install_platform() {
    run_script_logged "Platform Bootstrap" "$SCRIPT_DIR/setup_dev_env.sh"
}

function install_data() {
    run_script_logged "Data Services" "$SCRIPT_DIR/setup_data_tools.sh"
}

function install_security() {
    run_script_logged "Security Services" "$SCRIPT_DIR/setup_security_tools.sh"
}

function install_iam() {
    run_script_logged "IAM Services" "$SCRIPT_DIR/setup_iam.sh"
}

function install_observability() {
    run_script_logged "Observability Stack" "$SCRIPT_DIR/setup_observability.sh"
}

function install_gis() {
    run_script_logged "GIS Services" "$SCRIPT_DIR/setup_gis.sh"
}

function install_rancher() {
    run_script_logged "Rancher UI" "$SCRIPT_DIR/setup_rancher.sh"
}

function install_ingress() {
    run_script_logged "Ingress Configuration" "$SCRIPT_DIR/setup_ingress.sh"
}

function install_druppie() {
    run_script_logged "Druppie" "$SCRIPT_DIR/install_druppie.sh"
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
    while [[ $# -gt 0 ]]; do
        local choice=$1
        # Special logic for Uninstall with arguments (e.g. u k3d or ua k3d)
        if [[ "$choice" == "u" || "$choice" == "ua" ]]; then
             # Check if next arg exists and matches known uninstall targets or generic args
             # Assuming next arg is the parameters for uninstall
             if [[ -n "$2" && ! "$2" =~ ^-|[0-9]$ ]]; then
                 # If next arg is likely a keyword like k3d or rke2
                  execute_choice "$choice" "$2"
                  shift 2
                  continue
             elif [[ -n "$2" && "$2" =~ ^(1|2)$ ]]; then
                  # If next arg is 1 or 2
                  execute_choice "$choice" "$2"
                  shift 2
                  continue
             fi
        fi
        
        execute_choice "$choice"
        shift
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

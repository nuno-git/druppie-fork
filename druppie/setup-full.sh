#!/bin/bash
# =============================================================================
# Druppie Platform v2 - Full Stack Setup
# =============================================================================
# Complete standalone setup with Keycloak on NEW PORTS
#
# Ports:
#   - Keycloak: 8180
#   - Backend:  8100
#   - Frontend: 5273
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# Docker compose file
COMPOSE_FILE="docker-compose.full.yml"

# Keycloak settings for new port
KEYCLOAK_URL="http://localhost:8180"
KEYCLOAK_ADMIN="admin"
KEYCLOAK_ADMIN_PASSWORD="admin"
REALM_NAME="druppie"

# =============================================================================
# KEYCLOAK CONFIGURATION
# =============================================================================

wait_for_keycloak() {
    log "Waiting for Keycloak to be ready (this may take 2-3 minutes)..."

    for i in {1..60}; do
        if curl -sf "${KEYCLOAK_URL}/health/ready" > /dev/null 2>&1; then
            success "Keycloak is ready!"
            return 0
        fi
        echo -n "."
        sleep 5
    done

    error "Keycloak failed to start"
}

get_admin_token() {
    log "Getting Keycloak admin token..."

    TOKEN=$(curl -sf -X POST "${KEYCLOAK_URL}/realms/master/protocol/openid-connect/token" \
        -H "Content-Type: application/x-www-form-urlencoded" \
        -d "grant_type=password" \
        -d "client_id=admin-cli" \
        -d "username=${KEYCLOAK_ADMIN}" \
        -d "password=${KEYCLOAK_ADMIN_PASSWORD}" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

    if [ -z "$TOKEN" ]; then
        error "Failed to get admin token"
    fi

    success "Got admin token"
}

create_realm() {
    log "Creating realm '${REALM_NAME}'..."

    RESULT=$(curl -sf -o /dev/null -w "%{http_code}" -X POST "${KEYCLOAK_URL}/admin/realms" \
        -H "Authorization: Bearer ${TOKEN}" \
        -H "Content-Type: application/json" \
        -d '{
            "realm": "'"${REALM_NAME}"'",
            "enabled": true,
            "displayName": "Druppie Governance Platform",
            "registrationAllowed": false,
            "resetPasswordAllowed": true,
            "rememberMe": true,
            "loginWithEmailAllowed": true
        }')

    if [ "$RESULT" = "201" ] || [ "$RESULT" = "409" ]; then
        success "Realm '${REALM_NAME}' ready"
    else
        warn "Realm creation returned: $RESULT"
    fi
}

create_roles() {
    log "Creating roles..."

    for role in admin developer architect infra-engineer product-owner compliance-officer viewer; do
        curl -sf -o /dev/null -X POST "${KEYCLOAK_URL}/admin/realms/${REALM_NAME}/roles" \
            -H "Authorization: Bearer ${TOKEN}" \
            -H "Content-Type: application/json" \
            -d '{"name": "'"$role"'"}' 2>/dev/null || true
        echo -n "."
    done
    echo ""
    success "Roles created"
}

create_user() {
    local username="$1"
    local password="$2"
    local firstName="$3"
    local lastName="$4"
    local roles="$5"

    # Create user
    curl -sf -o /dev/null -X POST "${KEYCLOAK_URL}/admin/realms/${REALM_NAME}/users" \
        -H "Authorization: Bearer ${TOKEN}" \
        -H "Content-Type: application/json" \
        -d '{
            "username": "'"$username"'",
            "email": "'"$username"'@druppie.local",
            "firstName": "'"$firstName"'",
            "lastName": "'"$lastName"'",
            "enabled": true,
            "emailVerified": true,
            "credentials": [{"type": "password", "value": "'"$password"'", "temporary": false}]
        }' 2>/dev/null || true

    # Get user ID
    USER_ID=$(curl -sf "${KEYCLOAK_URL}/admin/realms/${REALM_NAME}/users?username=${username}" \
        -H "Authorization: Bearer ${TOKEN}" | python3 -c "import sys,json; users=json.load(sys.stdin); print(users[0]['id'] if users else '')" 2>/dev/null)

    if [ -n "$USER_ID" ]; then
        # Get role representations
        for role in $roles; do
            ROLE_REP=$(curl -sf "${KEYCLOAK_URL}/admin/realms/${REALM_NAME}/roles/${role}" \
                -H "Authorization: Bearer ${TOKEN}" 2>/dev/null)

            if [ -n "$ROLE_REP" ]; then
                curl -sf -o /dev/null -X POST "${KEYCLOAK_URL}/admin/realms/${REALM_NAME}/users/${USER_ID}/role-mappings/realm" \
                    -H "Authorization: Bearer ${TOKEN}" \
                    -H "Content-Type: application/json" \
                    -d "[${ROLE_REP}]" 2>/dev/null || true
            fi
        done
    fi
}

create_users() {
    log "Creating users..."

    create_user "admin" "Admin123!" "Admin" "User" "admin developer architect"
    create_user "seniordev" "Developer123!" "Senior" "Developer" "developer"
    create_user "juniordev" "Developer123!" "Junior" "Developer" "developer"
    create_user "architect" "Architect123!" "System" "Architect" "architect developer"

    success "Users created"
}

create_clients() {
    log "Creating OAuth2 clients..."

    # Frontend client (public) - note the new port 5273
    curl -sf -o /dev/null -X POST "${KEYCLOAK_URL}/admin/realms/${REALM_NAME}/clients" \
        -H "Authorization: Bearer ${TOKEN}" \
        -H "Content-Type: application/json" \
        -d '{
            "clientId": "druppie-frontend",
            "name": "Druppie Frontend",
            "publicClient": true,
            "standardFlowEnabled": true,
            "directAccessGrantsEnabled": true,
            "rootUrl": "http://localhost:5273",
            "redirectUris": ["http://localhost:5273/*"],
            "webOrigins": ["http://localhost:5273", "http://localhost:5173"]
        }' 2>/dev/null || true

    # Backend client (confidential)
    curl -sf -o /dev/null -X POST "${KEYCLOAK_URL}/admin/realms/${REALM_NAME}/clients" \
        -H "Authorization: Bearer ${TOKEN}" \
        -H "Content-Type: application/json" \
        -d '{
            "clientId": "druppie-backend",
            "name": "Druppie Backend API",
            "publicClient": false,
            "standardFlowEnabled": false,
            "serviceAccountsEnabled": true,
            "directAccessGrantsEnabled": true
        }' 2>/dev/null || true

    success "Clients created"
}

configure_keycloak() {
    get_admin_token
    create_realm
    create_roles
    create_users
    create_clients
}

# =============================================================================
# MAIN
# =============================================================================

start_stack() {
    log "Starting full stack with docker-compose..."

    # Build and start
    docker compose -f "$COMPOSE_FILE" build
    docker compose -f "$COMPOSE_FILE" up -d

    # Wait for Keycloak
    wait_for_keycloak

    # Configure Keycloak
    configure_keycloak

    # Wait for backend
    log "Waiting for backend..."
    for i in {1..30}; do
        if curl -sf http://localhost:8100/health > /dev/null 2>&1; then
            success "Backend is ready!"
            break
        fi
        echo -n "."
        sleep 2
    done
    echo ""

    # Wait for frontend
    log "Waiting for frontend..."
    for i in {1..30}; do
        if curl -sf http://localhost:5273 > /dev/null 2>&1; then
            success "Frontend is ready!"
            break
        fi
        echo -n "."
        sleep 2
    done
    echo ""

    print_summary
}

stop_stack() {
    log "Stopping stack..."
    docker compose -f "$COMPOSE_FILE" down
    success "Stopped"
}

clean_stack() {
    warn "This will delete all data!"
    read -p "Are you sure? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        docker compose -f "$COMPOSE_FILE" down -v
        success "Cleaned"
    fi
}

print_summary() {
    echo ""
    echo "============================================================================="
    echo -e "${GREEN}Druppie v2 Full Stack Ready!${NC}"
    echo "============================================================================="
    echo ""
    echo "Services:"
    echo "  - Frontend:  http://localhost:5273"
    echo "  - Backend:   http://localhost:8100"
    echo "  - API Docs:  http://localhost:8100/docs"
    echo "  - Keycloak:  http://localhost:8180"
    echo ""
    echo "Test Users:"
    echo "  - admin / Admin123!         (Full admin access)"
    echo "  - seniordev / Developer123! (Developer role)"
    echo "  - juniordev / Developer123! (Developer role)"
    echo "  - architect / Architect123! (Architect + Developer)"
    echo ""
    echo "Keycloak Admin:"
    echo "  - admin / admin"
    echo ""
    echo "Commands:"
    echo "  ./setup-full.sh stop   - Stop all services"
    echo "  ./setup-full.sh logs   - View logs"
    echo "  ./setup-full.sh clean  - Remove all data"
    echo "============================================================================="
}

case "${1:-start}" in
    start)
        start_stack
        ;;
    stop)
        stop_stack
        ;;
    logs)
        docker compose -f "$COMPOSE_FILE" logs -f "${2:-}"
        ;;
    clean)
        clean_stack
        ;;
    status)
        docker compose -f "$COMPOSE_FILE" ps
        ;;
    *)
        echo "Usage: $0 {start|stop|logs|clean|status}"
        ;;
esac

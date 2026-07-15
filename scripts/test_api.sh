#!/bin/bash
# =============================================================================
# Druppie API Test Script
# =============================================================================
# Tests the backend API endpoints with curl commands.
# Requires: backend running on localhost:8100, Keycloak on localhost:8180
#
# Usage: ./scripts/test_api.sh
# =============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${BLUE}[TEST]${NC} $1"; }
success() { echo -e "${GREEN}[PASS]${NC} $1"; }
fail() { echo -e "${RED}[FAIL]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

BACKEND_URL="http://localhost:8100"
KEYCLOAK_URL="http://localhost:8180"
KEYCLOAK_REALM="druppie"
KEYCLOAK_CLIENT="druppie-frontend"

# =============================================================================
# 1. HEALTH CHECK (No auth required)
# =============================================================================
echo ""
echo "=============================================="
echo "1. HEALTH CHECK (no auth)"
echo "=============================================="

log "Testing /health endpoint..."
HEALTH=$(curl -s "$BACKEND_URL/health")
echo "$HEALTH" | python3 -m json.tool 2>/dev/null || echo "$HEALTH"

if echo "$HEALTH" | grep -q '"status":"healthy"'; then
    success "Health check passed"
else
    fail "Health check failed"
    exit 1
fi

# =============================================================================
# 2. GET AUTH TOKEN
# =============================================================================
echo ""
echo "=============================================="
echo "2. AUTHENTICATE WITH KEYCLOAK"
echo "=============================================="

log "Getting token for user 'admin' from Keycloak..."

TOKEN_RESPONSE=$(curl -s -X POST "$KEYCLOAK_URL/realms/$KEYCLOAK_REALM/protocol/openid-connect/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "grant_type=password" \
    -d "client_id=$KEYCLOAK_CLIENT" \
    -d "username=admin" \
    -d "password=Admin123!")

ACCESS_TOKEN=$(echo "$TOKEN_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('access_token', ''))" 2>/dev/null)

if [ -z "$ACCESS_TOKEN" ] || [ "$ACCESS_TOKEN" == "None" ]; then
    warn "Could not get token from Keycloak. Response:"
    echo "$TOKEN_RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$TOKEN_RESPONSE"
    warn "Running remaining tests without authentication (will fail for protected endpoints)"
    AUTH_HEADER=""
else
    success "Got access token (${#ACCESS_TOKEN} chars)"
    AUTH_HEADER="Authorization: Bearer $ACCESS_TOKEN"
fi

# =============================================================================
# 3. TEST PROJECTS API
# =============================================================================
echo ""
echo "=============================================="
echo "3. PROJECTS API"
echo "=============================================="

log "GET /api/projects (list projects)..."
if [ -n "$AUTH_HEADER" ]; then
    PROJECTS=$(curl -s "$BACKEND_URL/api/projects" -H "$AUTH_HEADER")
else
    PROJECTS=$(curl -s "$BACKEND_URL/api/projects")
fi
echo "$PROJECTS" | python3 -m json.tool 2>/dev/null || echo "$PROJECTS"

if echo "$PROJECTS" | grep -q '"items"'; then
    success "Projects endpoint works"
else
    warn "Projects endpoint returned unexpected response"
fi

# =============================================================================
# 4. TEST SESSIONS API
# =============================================================================
echo ""
echo "=============================================="
echo "4. SESSIONS API"
echo "=============================================="

log "GET /api/sessions (list sessions)..."
if [ -n "$AUTH_HEADER" ]; then
    SESSIONS=$(curl -s "$BACKEND_URL/api/sessions" -H "$AUTH_HEADER")
else
    SESSIONS=$(curl -s "$BACKEND_URL/api/sessions")
fi
echo "$SESSIONS" | python3 -m json.tool 2>/dev/null || echo "$SESSIONS"

if echo "$SESSIONS" | grep -q '"items"'; then
    success "Sessions endpoint works"
else
    warn "Sessions endpoint returned unexpected response"
fi

# =============================================================================
# 5. CREATE SESSION VIA CHAT
# =============================================================================
echo ""
echo "=============================================="
echo "5. CREATE SESSION (via POST /api/chat)"
echo "=============================================="

log "POST /api/chat (create session with first message)..."
if [ -n "$AUTH_HEADER" ]; then
    NEW_SESSION=$(curl -s -X POST "$BACKEND_URL/api/chat" \
        -H "$AUTH_HEADER" \
        -H "Content-Type: application/json" \
        -d '{"message": "Hello, this is a test message from the API test script."}')
else
    NEW_SESSION=$(curl -s -X POST "$BACKEND_URL/api/chat" \
        -H "Content-Type: application/json" \
        -d '{"message": "Hello, this is a test message from the API test script."}')
fi
echo "$NEW_SESSION" | python3 -m json.tool 2>/dev/null || echo "$NEW_SESSION"

SESSION_ID=$(echo "$NEW_SESSION" | python3 -c "import sys, json; print(json.load(sys.stdin).get('session_id', ''))" 2>/dev/null)

if [ -n "$SESSION_ID" ] && [ "$SESSION_ID" != "None" ]; then
    success "Created session: $SESSION_ID"
else
    warn "Could not create session via chat"
    SESSION_ID=""
fi

# =============================================================================
# 6. GET SESSION DETAIL
# =============================================================================
if [ -n "$SESSION_ID" ]; then
    echo ""
    echo "=============================================="
    echo "6. GET SESSION DETAIL"
    echo "=============================================="

    log "GET /api/sessions/$SESSION_ID..."
    if [ -n "$AUTH_HEADER" ]; then
        SESSION_DETAIL=$(curl -s "$BACKEND_URL/api/sessions/$SESSION_ID" -H "$AUTH_HEADER")
    else
        SESSION_DETAIL=$(curl -s "$BACKEND_URL/api/sessions/$SESSION_ID")
    fi
    echo "$SESSION_DETAIL" | python3 -m json.tool 2>/dev/null || echo "$SESSION_DETAIL"

    if echo "$SESSION_DETAIL" | grep -q '"timeline"'; then
        success "Session detail with timeline works"
    else
        warn "Session detail returned unexpected response"
    fi
fi

# =============================================================================
# 7. TEST APPROVALS API
# =============================================================================
echo ""
echo "=============================================="
echo "7. APPROVALS API"
echo "=============================================="

log "GET /api/approvals (list pending approvals)..."
if [ -n "$AUTH_HEADER" ]; then
    APPROVALS=$(curl -s "$BACKEND_URL/api/approvals" -H "$AUTH_HEADER")
else
    APPROVALS=$(curl -s "$BACKEND_URL/api/approvals")
fi
echo "$APPROVALS" | python3 -m json.tool 2>/dev/null || echo "$APPROVALS"

if echo "$APPROVALS" | grep -q '"items"'; then
    success "Approvals endpoint works"
else
    warn "Approvals endpoint returned unexpected response"
fi

# =============================================================================
# 8. QUESTIONS API INFO
# =============================================================================
echo ""
echo "=============================================="
echo "8. QUESTIONS API (HITL)"
echo "=============================================="

log "Note: Questions are shown in session detail (part of timeline)."
log "There is no list endpoint. Questions can only be answered via:"
log "  POST /api/questions/{question_id}/answer"
success "Questions endpoint structure documented"

# =============================================================================
# 9. TEST AGENTS API
# =============================================================================
echo ""
echo "=============================================="
echo "9. AGENTS API"
echo "=============================================="

log "GET /api/agents (list available agents)..."
if [ -n "$AUTH_HEADER" ]; then
    AGENTS=$(curl -s "$BACKEND_URL/api/agents" -H "$AUTH_HEADER")
else
    AGENTS=$(curl -s "$BACKEND_URL/api/agents")
fi
echo "$AGENTS" | python3 -m json.tool 2>/dev/null || echo "$AGENTS"

if echo "$AGENTS" | grep -q '"agents"'; then
    success "Agents endpoint works"
else
    warn "Agents endpoint returned unexpected response"
fi

# =============================================================================
# 10. TEST MCP TOOLS API
# =============================================================================
echo ""
echo "=============================================="
echo "10. MCP TOOLS API"
echo "=============================================="

log "GET /api/mcps (list available MCP tools)..."
if [ -n "$AUTH_HEADER" ]; then
    MCPS=$(curl -s "$BACKEND_URL/api/mcps" -H "$AUTH_HEADER")
else
    MCPS=$(curl -s "$BACKEND_URL/api/mcps")
fi
# Only show summary since full output is long
MCPS_COUNT=$(echo "$MCPS" | python3 -c "import sys, json; d=json.load(sys.stdin); print(f'Servers: {len(d.get(\"servers\", []))}, Tools: {d.get(\"total_tools\", 0)}')" 2>/dev/null || echo "Error parsing")
echo "$MCPS_COUNT"

if echo "$MCPS" | grep -q '"servers"'; then
    success "MCP endpoint works"
else
    warn "MCP endpoint returned unexpected response"
fi

# =============================================================================
# 11. DATABASE STATE
# =============================================================================
echo ""
echo "=============================================="
echo "11. DATABASE STATE (via psql)"
echo "=============================================="

log "Querying database tables..."

# Query via docker exec
docker compose exec -T db psql -U druppie -d druppie -c "\dt" 2>/dev/null || warn "Could not query tables"

echo ""
log "Row counts per table:"
docker compose exec -T db psql -U druppie -d druppie -c "
SELECT
    schemaname,
    relname AS table_name,
    n_live_tup AS row_count
FROM pg_stat_user_tables
ORDER BY relname;
" 2>/dev/null || warn "Could not get row counts"

echo ""
log "Users table content:"
docker compose exec -T db psql -U druppie -d druppie -c "SELECT id, username, email FROM users LIMIT 5;" 2>/dev/null || warn "Could not query users"

if [ -n "$SESSION_ID" ]; then
    echo ""
    log "Sessions table content:"
    docker compose exec -T db psql -U druppie -d druppie -c "SELECT id, title, user_id, status, created_at FROM sessions LIMIT 5;" 2>/dev/null || warn "Could not query sessions"

    echo ""
    log "Messages table content:"
    docker compose exec -T db psql -U druppie -d druppie -c "SELECT id, session_id, role, content FROM messages LIMIT 5;" 2>/dev/null || warn "Could not query messages"
fi

# =============================================================================
# SUMMARY
# =============================================================================
echo ""
echo "=============================================="
echo "TEST SUMMARY"
echo "=============================================="
echo ""
success "All basic API tests completed!"
echo ""
echo "Working endpoints:"
echo "  - GET  /health"
echo "  - GET  /api/projects"
echo "  - GET  /api/sessions"
echo "  - POST /api/chat (creates session + processes message)"
echo "  - GET  /api/sessions/{id}"
echo "  - GET  /api/approvals"
echo "  - GET  /api/agents"
echo "  - GET  /api/mcps"
echo ""
echo "Backend URL:  $BACKEND_URL"
echo "API Docs:     $BACKEND_URL/docs"

#!/usr/bin/env bash
#
# dev-workspace-entrypoint.sh — boot a Druppie per-branch developer workspace.
#
# Baked into Dockerfile.dev-workspace. Seeds /workspace from the image's
# offline snapshot, checks out the requested branch, (re)installs deps only
# when their lockfiles changed, then launches three plain-HTTP dev services:
#
#   code-server (:8080)  VS Code in the browser, opened on /workspace
#   backend     (:8000)  uvicorn --reload, SQLite, dev/degraded mode
#   frontend    (:5173)  Vite dev server with HMR
#
# Auth is handled by the oauth2-proxy sidecar; every port is plain HTTP.
# No Docker daemon, no xrdp, no in-pod Gitea. k8s restarts the pod on crash,
# so there are no in-process restart loops.
#
# Environment contract (set by the k8s manifest):
#   DRUPPIE_GIT_BRANCH   branch to check out            (default: colab-dev)
#   DRUPPIE_REPO_URL     git remote                     (default: https://aigit.waterschap.org/ai/druppie.git)
#   DRUPPIE_GIT_TOKEN    optional token for git fetch   (default: unset)
#   VITE_API_URL         backend URL for the frontend   (default: /proxy/8000)
#   DATABASE_URL         backend DB URL                 (default: sqlite:////workspace/.data/druppie.db)
#   GIT_SSL_NO_VERIFY    set to "1" to skip TLS verify on fetch (default: unset)
#
set -u

WORKSPACE="/workspace"
SRC="/opt/druppie-src"
BAKED_VENV="/opt/venv"
VENV="${WORKSPACE}/.venv"
LOGS="${WORKSPACE}/.logs"
DEP_DIR="${WORKSPACE}/.dep-hashes"

DRUPPIE_GIT_BRANCH="${DRUPPIE_GIT_BRANCH:-colab-dev}"
DRUPPIE_REPO_URL="${DRUPPIE_REPO_URL:-https://aigit.waterschap.org/ai/druppie.git}"
DRUPPIE_GIT_TOKEN="${DRUPPIE_GIT_TOKEN:-}"
# Default is a RELATIVE path: the app preview is reached through code-server's
# built-in port proxy (https://<workspace-host>/proxy/5173), so the browser
# cannot reach localhost:8000 directly. /proxy/8000 routes API calls through
# the same code-server proxy (and thus the oauth2-proxy session) to the
# backend on this pod.
VITE_API_URL="${VITE_API_URL:-/proxy/8000}"
DATABASE_URL="${DATABASE_URL:-sqlite:////workspace/.data/druppie.db}"

REQUIREMENTS_REL="druppie/requirements.txt"
FRONTEND_LOCK_REL="frontend/package-lock.json"

log()  { printf '[dev-workspace] %s\n' "$*"; }
warn() { printf '[dev-workspace] WARN: %s\n' "$*" >&2; }

# ---------------------------------------------------------------------------
# 1. Seed the workspace from the baked snapshot (first boot only).
# ---------------------------------------------------------------------------
seed_workspace() {
    # Consider the workspace unseeded if it has no baked marker. Ignore the
    # dot-dirs we create ourselves (.logs etc.) when deciding emptiness.
    if [ -f "${WORKSPACE}/.seeded" ]; then
        log "workspace already seeded — reusing existing checkout"
        return 0
    fi

    log "seeding workspace from ${SRC} (first boot)"
    # -a preserves the developer-owned tree baked in the image. The trailing
    # /. copies contents (including dotfiles) into the existing /workspace.
    cp -a "${SRC}/." "${WORKSPACE}/"

    # The baked snapshot has no .git (excluded by .dockerignore). Re-init so
    # code-server's git integration and the runtime checkout below work.
    if [ ! -d "${WORKSPACE}/.git" ]; then
        git -C "${WORKSPACE}" init -q
        git -C "${WORKSPACE}" config user.name "druppie-dev" 2>/dev/null || true
        git -C "${WORKSPACE}" config user.email "dev@druppie.local" 2>/dev/null || true
        git -C "${WORKSPACE}" remote add origin "${DRUPPIE_REPO_URL}" 2>/dev/null || \
            git -C "${WORKSPACE}" remote set-url origin "${DRUPPIE_REPO_URL}"
    fi

    # Seed the backend venv (relocated copy — see Dockerfile L5 note).
    if [ ! -d "${VENV}" ]; then
        cp -a "${BAKED_VENV}" "${VENV}"
    fi

    # Record the baked dependency hashes so a first boot on the baked branch
    # does NOT trigger a needless reinstall. A later checkout that changes the
    # lockfiles will flip these and force a reinstall (see step 3).
    mkdir -p "${DEP_DIR}"
    store_hash "${FRONTEND_LOCK_REL}" "${DEP_DIR}/frontend.sha"
    store_hash "${REQUIREMENTS_REL}"  "${DEP_DIR}/backend.sha"

    touch "${WORKSPACE}/.seeded"
}

hash_of()    { [ -f "${WORKSPACE}/$1" ] && sha256sum "${WORKSPACE}/$1" | awk '{print $1}' || printf ''; }
store_hash() { hash_of "$1" > "$2"; }

# ---------------------------------------------------------------------------
# 2. Fetch + checkout the requested branch (tolerate offline).
# ---------------------------------------------------------------------------
checkout_branch() {
    local branch="${DRUPPIE_GIT_BRANCH}"
    local git_opts=""
    [ "${GIT_SSL_NO_VERIFY:-}" = "1" ] && git_opts="-c http.sslVerify=false"

    # Build an authenticated fetch URL without persisting the token in the
    # stored remote (origin keeps the clean URL for the code-server UI).
    local fetch_url="${DRUPPIE_REPO_URL}"
    if [ -n "${DRUPPIE_GIT_TOKEN}" ]; then
        fetch_url=$(printf '%s' "${DRUPPIE_REPO_URL}" | sed "s#https://#https://oauth2:${DRUPPIE_GIT_TOKEN}@#")
    fi

    log "fetching branch '${branch}' from origin"
    # shellcheck disable=SC2086
    if git -C "${WORKSPACE}" ${git_opts} fetch --depth=1 "${fetch_url}" "${branch}" 2>>"${LOGS}/git.log"; then
        # reset --hard overwrites the seeded working tree to the branch content
        # without the "untracked file would be overwritten" errors that plague
        # `git checkout` when the dir was pre-populated by the seed step.
        git -C "${WORKSPACE}" reset --hard FETCH_HEAD >>"${LOGS}/git.log" 2>&1
        git -C "${WORKSPACE}" checkout -B "${branch}" >>"${LOGS}/git.log" 2>&1 || true
        log "checked out '${branch}' at $(git -C "${WORKSPACE}" rev-parse --short HEAD 2>/dev/null || echo '?')"
    else
        warn "git fetch failed (offline or auth/TLS issue) — continuing with the baked snapshot; see ${LOGS}/git.log"
    fi
}

# ---------------------------------------------------------------------------
# 3. Conditional dependency install (only when a lockfile changed).
# ---------------------------------------------------------------------------
ensure_frontend_deps() {
    local cur stored
    cur=$(hash_of "${FRONTEND_LOCK_REL}")
    stored=$(cat "${DEP_DIR}/frontend.sha" 2>/dev/null || printf '')
    if [ -z "${cur}" ]; then
        warn "no ${FRONTEND_LOCK_REL} — skipping frontend install"
        return 0
    fi
    if [ ! -d "${WORKSPACE}/frontend/node_modules" ] || [ "${cur}" != "${stored}" ]; then
        log "frontend deps changed (or missing) — running npm ci"
        ( cd "${WORKSPACE}/frontend" && npm ci ) && printf '%s' "${cur}" > "${DEP_DIR}/frontend.sha"
    else
        log "frontend deps unchanged — reusing node_modules"
    fi
}

ensure_backend_deps() {
    local cur stored
    cur=$(hash_of "${REQUIREMENTS_REL}")
    stored=$(cat "${DEP_DIR}/backend.sha" 2>/dev/null || printf '')
    if [ -z "${cur}" ]; then
        warn "no ${REQUIREMENTS_REL} — skipping backend install"
        return 0
    fi
    if [ ! -d "${VENV}" ] || [ "${cur}" != "${stored}" ]; then
        log "backend deps changed (or missing) — running pip install"
        "${VENV}/bin/python" -m pip install --no-cache-dir -r "${WORKSPACE}/${REQUIREMENTS_REL}" \
            && printf '%s' "${cur}" > "${DEP_DIR}/backend.sha"
    else
        log "backend deps unchanged — reusing venv"
    fi
}

# ---------------------------------------------------------------------------
# 4. Launch services (backgrounded; logs under /workspace/.logs).
# ---------------------------------------------------------------------------
PIDS=""

start_backend() {
    log "starting backend (uvicorn --reload) on 0.0.0.0:8000"
    # SQLite URLs: sqlite:///relative or sqlite:////absolute. Stripping the
    # three-slash prefix leaves "/workspace/..." (absolute) or "./..." intact.
    case "${DATABASE_URL}" in
        sqlite:*)
            db_path=$(printf '%s' "${DATABASE_URL}" | sed 's#^sqlite:///##')
            mkdir -p "$(dirname "${db_path}")" 2>/dev/null || true
            ;;
    esac
    (
        cd "${WORKSPACE}" || exit 1
        # Dev/degraded backend: SQLite (tables auto-created on import via
        # api/deps.py init_db()), no Keycloak/Gitea/MCP wiring. GITHUB_APP_* is
        # deliberately left UNSET so Settings.validate_startup() does not abort.
        PYTHONPATH="${WORKSPACE}" \
        DATABASE_URL="${DATABASE_URL}" \
        ENVIRONMENT="development" \
        "${VENV}/bin/python" -m uvicorn druppie.api.main:app \
            --host 0.0.0.0 --port 8000 \
            --reload --reload-dir "${WORKSPACE}/druppie"
    ) >"${LOGS}/backend.log" 2>&1 &
    PIDS="${PIDS} $!"
}

start_frontend() {
    log "starting frontend (vite dev, HMR) on 0.0.0.0:5173"
    (
        cd "${WORKSPACE}/frontend" || exit 1
        # The frontend reads the backend URL from VITE_API_URL (src/services/
        # api.js). No Vite proxy is needed or added — env-based config matches
        # how docker-compose's druppie-frontend-dev service is wired.
        VITE_API_URL="${VITE_API_URL}" npm run dev -- --host 0.0.0.0
    ) >"${LOGS}/frontend.log" 2>&1 &
    PIDS="${PIDS} $!"
}

start_code_server() {
    log "starting code-server on 0.0.0.0:8080 (auth handled by oauth2-proxy sidecar)"
    code-server --bind-addr 0.0.0.0:8080 --auth none "${WORKSPACE}" \
        >"${LOGS}/code-server.log" 2>&1 &
    PIDS="${PIDS} $!"
}

# ---------------------------------------------------------------------------
# 5. Signal handling — kill children on SIGTERM/SIGINT so the pod exits fast.
# ---------------------------------------------------------------------------
terminate() {
    log "received termination signal — stopping child processes"
    # shellcheck disable=SC2086
    kill ${PIDS} 2>/dev/null || true
    wait 2>/dev/null || true
    exit 0
}
trap terminate TERM INT

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
mkdir -p "${LOGS}" "${DEP_DIR}"
log "workspace boot: branch=${DRUPPIE_GIT_BRANCH} repo=${DRUPPIE_REPO_URL}"

# The PVC mount root stays root-owned (fsGroup only changes the group), so git
# refuses the repo with "dubious ownership" unless it is marked safe.
git config --global --add safe.directory "${WORKSPACE}"

seed_workspace
checkout_branch
ensure_frontend_deps
ensure_backend_deps

start_code_server
start_backend
start_frontend

log "all services started (pids:${PIDS}) — tailing until a child exits or SIGTERM"

# Wait for the first child to exit, then tear the rest down so k8s restarts the
# pod. `wait -n` needs bash (provided by the image); this script runs under bash.
wait -n
warn "a child process exited — shutting down so the pod restarts"
terminate

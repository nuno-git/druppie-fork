#!/usr/bin/env bash
#
# dev-workspace-entrypoint.sh — boot a Druppie per-branch developer workspace.
#
# Baked into Dockerfile.dev-workspace. Seeds /workspace from the image's
# offline snapshot, checks out the requested branch, (re)installs deps only
# when their lockfiles changed, then launches the plain-HTTP dev services:
#
#   code-server (:8080)  VS Code in the browser, opened on /workspace
#   backend     (:8000)  uvicorn --reload, SQLite, dev/degraded mode
#   frontend    (:5173)  Vite dev server with HMR
#   desktop     (:6080)  XFCE over noVNC, 127.0.0.1 only — open
#                        https://<workspace-host>/proxy/6080/ (code-server's
#                        authenticated port proxy)
#
# Auth is handled by the oauth2-proxy sidecar; every port is plain HTTP.
# No Docker daemon, no xrdp, no in-pod Gitea. k8s restarts the pod on crash,
# so there are no in-process restart loops (the XFCE session respawn loop is
# the one exception: "Log out" must not take the whole pod down).
#
# Environment contract (set by the k8s manifest):
#   DRUPPIE_GIT_BRANCH   branch to check out            (default: colab-dev)
#   DRUPPIE_REPO_URL     git remote                     (default: https://aigit.waterschap.org/ai/druppie.git)
#   DRUPPIE_GIT_TOKEN    optional token for git fetch   (default: unset)
#   VITE_API_URL         backend URL for the frontend   (default: /proxy/8000)
#   DEV_STACK            real | degraded                (default: degraded)
#                        real = use chart-provided DATABASE_URL/KEYCLOAK_*/MCP_*
#                        degraded = force SQLite + mock (ignore inherited DATABASE_URL)
#   DATABASE_URL         backend DB URL (real mode)     (default: sqlite:////workspace/.data/druppie.db)
#   GIT_SSL_NO_VERIFY    set to "1" to skip TLS verify on fetch (default: unset)
#   DRUPPIE_DESKTOP      set to "0" to skip the XFCE/noVNC desktop (default: 1)
#   DRUPPIE_DESKTOP_GEOMETRY  initial Xvnc resolution   (default: 1600x900)
#
set -u

WORKSPACE="/workspace"
REPO_DIR="${WORKSPACE}/druppie"
SRC="/opt/druppie-src"
BAKED_VENV="/opt/venv"
VENV="${WORKSPACE}/.venv"
LOGS="${WORKSPACE}/.logs"
DEP_DIR="${WORKSPACE}/.dep-hashes"

DRUPPIE_GIT_BRANCH="${DRUPPIE_GIT_BRANCH:-colab-dev}"
DRUPPIE_REPO_URL="${DRUPPIE_REPO_URL:-https://aigit.waterschap.org/ai/druppie.git}"
DRUPPIE_GIT_TOKEN="${DRUPPIE_GIT_TOKEN:-}"
# DEV_STACK selects the backend's runtime dependencies:
#   real      = consume the deployed stack: DATABASE_URL / KEYCLOAK_* / MCP_* /
#               GITEA_* are provided by the chart (envFrom <instance>-config +
#               <instance>-secrets). The backend runs against real Postgres +
#               Keycloak, but still under `uvicorn --reload`.
#   degraded  = isolated: force SQLite + mock, ignore any incoming DATABASE_URL.
#               Fast, offline-friendly — the intended default when dev-env
#               creation exposes the choice.
DEV_STACK="${DEV_STACK:-degraded}"
# Default is a RELATIVE path: the app preview is reached through code-server's
# built-in port proxy (https://<workspace-host>/proxy/5173), so the browser
# cannot reach localhost:8000 directly. /proxy/8000 routes API calls through
# the same code-server proxy (and thus the oauth2-proxy session) to the
# backend on this pod.
VITE_API_URL="${VITE_API_URL:-/proxy/8000}"
# In degraded mode always use the local SQLite DB (ignore any DATABASE_URL
# inherited from the chart). In real mode honor the chart-provided DATABASE_URL
# and only fall back to SQLite if it is somehow unset.
if [ "${DEV_STACK}" = "real" ]; then
    DATABASE_URL="${DATABASE_URL:-sqlite:////workspace/.data/druppie.db}"
else
    DATABASE_URL="sqlite:////workspace/.data/druppie.db"
fi

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
    if [ -f "${REPO_DIR}/.seeded" ]; then
        log "workspace already seeded — reusing existing checkout"
        return 0
    fi

    log "seeding workspace from ${SRC} (first boot)"
    mkdir -p "${REPO_DIR}"
    # -a preserves the developer-owned tree baked in the image. The trailing
    # /. copies contents (including dotfiles) into ${REPO_DIR}.
    cp -a "${SRC}/." "${REPO_DIR}/"

    # The baked snapshot has no .git (excluded by .dockerignore). Re-init so
    # code-server's git integration and the runtime checkout below work.
    if [ ! -d "${REPO_DIR}/.git" ]; then
        git -C "${REPO_DIR}" init -q
        git -C "${REPO_DIR}" config user.name "druppie-dev" 2>/dev/null || true
        git -C "${REPO_DIR}" config user.email "dev@druppie.local" 2>/dev/null || true
        git -C "${REPO_DIR}" remote add origin "${DRUPPIE_REPO_URL}" 2>/dev/null || \
            git -C "${REPO_DIR}" remote set-url origin "${DRUPPIE_REPO_URL}"
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

    touch "${REPO_DIR}/.seeded"
}

hash_of()    { [ -f "${REPO_DIR}/$1" ] && sha256sum "${REPO_DIR}/$1" | awk '{print $1}' || printf ''; }
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
    local git_token="${DRUPPIE_GIT_TOKEN:-${EXTERNAL_GITEA_TOKEN:-}}"
    local fetch_url="${DRUPPIE_REPO_URL}"
    if [ -n "${git_token}" ]; then
        fetch_url=$(printf '%s' "${DRUPPIE_REPO_URL}" | sed "s#https://#https://oauth2:${git_token}@#")
    fi

    log "fetching branch '${branch}' from origin"
    # shellcheck disable=SC2086
    if git -C "${REPO_DIR}" ${git_opts} fetch --depth=1 "${fetch_url}" "${branch}" 2>>"${LOGS}/git.log"; then
        # reset --hard overwrites the seeded working tree to the branch content
        # without the "untracked file would be overwritten" errors that plague
        # `git checkout` when the dir was pre-populated by the seed step.
        git -C "${REPO_DIR}" reset --hard FETCH_HEAD >>"${LOGS}/git.log" 2>&1
        git -C "${REPO_DIR}" checkout -B "${branch}" >>"${LOGS}/git.log" 2>&1 || true
        log "checked out '${branch}' at $(git -C "${REPO_DIR}" rev-parse --short HEAD 2>/dev/null || echo '?')"
    else
        warn "git fetch failed (offline or auth/TLS issue) — continuing with the baked snapshot; see ${LOGS}/git.log"
    fi
}

# ---------------------------------------------------------------------------
# 2b. Configure git for push from code-server terminal.
# ---------------------------------------------------------------------------
configure_git() {
    git config --global user.name "Developer"
    git config --global user.email "dev@druppie.local"
    git config --global push.default current
    local git_token="${DRUPPIE_GIT_TOKEN:-${EXTERNAL_GITEA_TOKEN:-}}"
    if [ -n "${git_token}" ]; then
        printf 'https://oauth2:%s@aigit.waterschap.org\n' "${git_token}" > "${HOME}/.git-credentials"
        chmod 600 "${HOME}/.git-credentials"
        git config --global credential.helper store
        log "git configured with token-based auth for aigit.waterschap.org"
    else
        warn "no git token found (DRUPPIE_GIT_TOKEN or EXTERNAL_GITEA_TOKEN) — git push will fail without credentials"
    fi
}

# ---------------------------------------------------------------------------
# 2c. Clone supplementary repos (ai/k8s, systeembeheer/rancher-gitops).
# ---------------------------------------------------------------------------
clone_side_repos() {
    local git_token="${DRUPPIE_GIT_TOKEN:-${EXTERNAL_GITEA_TOKEN:-}}"
    if [ -z "${git_token}" ]; then
        warn "no git token — skipping side repo clones"
        return 0
    fi

    local side_repos=(
        "ai/k8s"
        "systeembeheer/rancher-gitops"
    )

    local git_opts=""
    [ "${GIT_SSL_NO_VERIFY:-}" = "1" ] && git_opts="-c http.sslVerify=false"

    for repo in "${side_repos[@]}"; do
        local dir="${WORKSPACE}/${repo//\//-}"
        if [ -d "${dir}/.git" ]; then
            log "side repo ${repo} already cloned — pulling latest"
            git -C "${dir}" ${git_opts} pull --ff-only origin main >>"${LOGS}/git.log" 2>&1 || \
                warn "could not update ${repo} — stale checkout"
        else
            log "cloning side repo ${repo} → ${dir}"
            git -C "${WORKSPACE}" ${git_opts} clone --depth=1 \
                "https://oauth2:${git_token}@aigit.waterschap.org/${repo}.git" \
                "${dir}" >>"${LOGS}/git.log" 2>&1 || \
                warn "could not clone ${repo}"
        fi
    done
}
ensure_frontend_deps() {
    local cur stored
    cur=$(hash_of "${FRONTEND_LOCK_REL}")
    stored=$(cat "${DEP_DIR}/frontend.sha" 2>/dev/null || printf '')
    if [ -z "${cur}" ]; then
        warn "no ${FRONTEND_LOCK_REL} — skipping frontend install"
        return 0
    fi
    if [ ! -d "${REPO_DIR}/frontend/node_modules" ] || [ "${cur}" != "${stored}" ]; then
        log "frontend deps changed (or missing) — running npm ci"
        ( cd "${REPO_DIR}/frontend" && npm ci ) && printf '%s' "${cur}" > "${DEP_DIR}/frontend.sha"
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
        "${VENV}/bin/python" -m pip install --no-cache-dir -r "${REPO_DIR}/${REQUIREMENTS_REL}" \
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
    log "starting backend (uvicorn --reload) on 0.0.0.0:8000 [DEV_STACK=${DEV_STACK}]"
    # SQLite URLs: sqlite:///relative or sqlite:////absolute. Stripping the
    # three-slash prefix leaves "/workspace/..." (absolute) or "./..." intact.
    case "${DATABASE_URL}" in
        sqlite:*)
            db_path=$(printf '%s' "${DATABASE_URL}" | sed 's#^sqlite:///##')
            mkdir -p "$(dirname "${db_path}")" 2>/dev/null || true
            ;;
    esac
    (
        cd "${REPO_DIR}" || exit 1
        # DEV_STACK=real: DATABASE_URL/KEYCLOAK_*/MCP_*/GITEA_* are provided by
        #   the chart (envFrom). The backend runs against the real deployed
        #   stack, still under --reload.
        # DEV_STACK=degraded: SQLite (tables auto-created on import via
        # api/deps.py init_db()), mock auth, no Keycloak/Gitea/MCP wiring.
        #   GITHUB_APP_* is deliberately left UNSET so Settings.validate_startup()
        #   does not abort.
        PYTHONPATH="${REPO_DIR}" \
        DATABASE_URL="${DATABASE_URL}" \
        ENVIRONMENT="development" \
        "${VENV}/bin/python" -m uvicorn druppie.api.main:app \
            --host 0.0.0.0 --port 8000 \
            --reload --reload-dir "${REPO_DIR}/druppie"
    ) >"${LOGS}/backend.log" 2>&1 &
    PIDS="${PIDS} $!"
}

start_frontend() {
    log "starting frontend (vite dev, HMR) on 0.0.0.0:5173"
    (
        cd "${REPO_DIR}/frontend" || exit 1
        # The frontend reads the backend URL from VITE_API_URL (src/services/
        # api.js). No Vite proxy is needed or added — env-based config matches
        # how docker-compose's druppie-frontend-dev service is wired.
        VITE_API_URL="${VITE_API_URL}" npm run dev -- --host 0.0.0.0
    ) >"${LOGS}/frontend.log" 2>&1 &
    PIDS="${PIDS} $!"
}

start_desktop() {
    if [ "${DRUPPIE_DESKTOP:-1}" != "1" ]; then
        log "DRUPPIE_DESKTOP=${DRUPPIE_DESKTOP:-} — desktop disabled"
        return 0
    fi
    # Pods can run an older image (pre-desktop) until dev-workspace:latest is
    # rebuilt; skip instead of crash-looping the whole workspace.
    if ! command -v Xvnc >/dev/null 2>&1; then
        warn "Xvnc not in this image — desktop disabled (rebuild dev-workspace)"
        return 0
    fi

    log "starting desktop (XFCE over noVNC) — open /proxy/6080/ on the workspace host"
    # 127.0.0.1 only and -SecurityTypes None: the ONLY way in is code-server's
    # authenticated port proxy, same trust model as code-server's auth:none.
    Xvnc :1 -geometry "${DRUPPIE_DESKTOP_GEOMETRY:-1600x900}" -depth 24 \
        -SecurityTypes None -localhost -AlwaysShared -rfbport 5901 \
        >"${LOGS}/xvnc.log" 2>&1 &
    PIDS="${PIDS} $!"

    # Respawn loop: an XFCE "Log out" (or session crash) restarts the session
    # instead of tearing down the pod via the wait -n below. The first
    # iterations fail fast until Xvnc is accepting connections — harmless.
    (
        export DISPLAY=:1
        while :; do
            dbus-launch --exit-with-session startxfce4 >>"${LOGS}/xfce.log" 2>&1
            sleep 2
        done
    ) &
    PIDS="${PIDS} $!"

    # noVNC static client + websocket bridge to Xvnc.
    websockify --web /opt/novnc-web 127.0.0.1:6080 127.0.0.1:5901 \
        >"${LOGS}/novnc.log" 2>&1 &
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
git config --global --add safe.directory "${REPO_DIR}"

# Claude Code: keep login/config on the PVC so it survives pod restarts.
export CLAUDE_CONFIG_DIR="${WORKSPACE}/.claude"
mkdir -p "${CLAUDE_CONFIG_DIR}"

seed_workspace

# Keep the workspace's own runtime artifacts out of the Source Control pane:
# they are per-pod state, not repo changes. Repo-local ignore (info/exclude)
# so the repo's .gitignore stays untouched. After seed_workspace: that step
# creates .git on first boot.
printf '.seeded\n.logs/\n.dep-hashes/\n.venv/\n.data/\n.claude/\n' \
    > "${REPO_DIR}/.git/info/exclude"

checkout_branch
configure_git
clone_side_repos
ensure_frontend_deps
ensure_backend_deps

start_code_server
start_backend
start_frontend
start_desktop

log "all services started (pids:${PIDS}) — tailing until a child exits or SIGTERM"

# Wait for the first child to exit, then tear the rest down so k8s restarts the
# pod. `wait -n` needs bash (provided by the image); this script runs under bash.
wait -n
warn "a child process exited — shutting down so the pod restarts"
terminate

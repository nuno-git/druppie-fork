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

# EMBED_MODULES: space-separated MCP module keys to run inside this pod under
# `uvicorn --reload` (hot-reload on edit). Set by the chart from
# devWorkspace.embedModules. Empty in prod/colab-dev and any workspace that
# keeps modules as baked-image Deployments.
EMBED_MODULES="${EMBED_MODULES:-}"

# Canonical MCP module catalog: values-key -> "source-dir port".
#   - source-dir is relative to druppie/mcp-servers/ (module-<key-with-_→->)
#   - port matches the chart's modules.<key>.port and the Service targetPort
# Keys here are the universe of embeddable modules; EMBED_MODULES selects which
# actually run. A missing /opt/venvs/<key> (build skipped in the image) makes
# start_mcp_module fall back to a runtime venv build, or skip with a warning.
declare -A MCP_MODULES=(
    [coding]="module-coding 9001"
    [docker]="module-docker 9002"
    [filesearch]="module-filesearch 9004"
    [web]="module-web 9005"
    [archimate]="module-archimate 9006"
    [registry]="module-registry 9007"
    [llm]="module-llm 9008"
    [kubernetes]="module-kubernetes 9013"
    [vision]="module-vision 9011"
    [searxng]="module-searxng 9014"
    [browser]="module-browser 9015"
    [data_access]="module-data-access 9010"
    [azuredevops]="module-azuredevops 9012"
)

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
# 3b. Embedded MCP modules — per-module venv + uvicorn --reload launcher.
# ---------------------------------------------------------------------------
# Each embedded module (EMBED_MODULES) runs as a backgrounded uvicorn --reload
# process against its live source under /workspace/druppie/mcp-servers/<dir>,
# so edits in code-server hot-reload the module exactly like the backend.
#
# Module source layout: server.py imports `module_router` (shared, lives one
# level up in mcp-servers/) and `v1.tools` (subdir of the module). We set
# PYTHONPATH=mcp-servers/ and cwd=module dir so both resolve — matching the
# flat /app layout the baked image produces via two COPYs.
ensure_mcp_module_deps() {
    # $1 = module key, $2 = module dir (under mcp-servers/). Reinstalls the
    # module's relocated venv when its requirements.txt changed since last boot
    # (or when the baked venv was absent — e.g. a module added after the image
    # was built, or one whose image-side install failed non-fatally).
    local key="$1" dir="$2"
    local req_rel="druppie/mcp-servers/${dir}/requirements.txt"
    local venv="${WORKSPACE}/.venvs/${key}"
    local sha_file="${DEP_DIR}/mcp-${key}.sha"
    local cur stored
    cur=$(hash_of "${req_rel}")
    if [ -z "${cur}" ]; then
        warn "mcp ${key}: no ${req_rel} — skipping deps check"
        return 0
    fi
    stored=$(cat "${sha_file}" 2>/dev/null || printf '')
    if [ ! -d "${venv}" ] || [ "${cur}" != "${stored}" ]; then
        log "mcp ${key}: deps changed (or venv missing) — pip install"
        if [ ! -d "${venv}" ]; then
            if ! "${VENV}/bin/python" -m venv "${venv}" \
                || ! "${venv}/bin/python" -m pip install --no-cache-dir --upgrade pip; then
                warn "mcp ${key}: venv create failed — module will not start"
                rm -rf "${venv}"
                return 1
            fi
        fi
        if "${venv}/bin/python" -m pip install --no-cache-dir -r "${REPO_DIR}/${req_rel}"; then
            printf '%s' "${cur}" > "${sha_file}"
        else
            warn "mcp ${key}: pip install failed — module may be broken until requirements fixed"
            return 1
        fi
    else
        log "mcp ${key}: deps unchanged — reusing venv"
    fi
}

start_mcp_module() {
    # $1 = module key. Resolves dir/port from the catalog, seeds the venv from
    # the baked snapshot if available, ensures deps, then launches uvicorn
    # --reload on the module's port. Watches the module's own dir only; a
    # shared module_router.py edit needs a manual workspace restart.
    local key="$1"
    local entry="${MCP_MODULES[${key}]:-}"
    if [ -z "${entry}" ]; then
        warn "unknown MCP module '${key}' — skipped (not in catalog)"
        return 0
    fi
    local dir port
    dir="${entry%% *}"
    port="${entry##* }"
    local mod_dir="${REPO_DIR}/druppie/mcp-servers/${dir}"
    local baked="/opt/venvs/${key}"
    local venv="${WORKSPACE}/.venvs/${key}"

    if [ ! -d "${mod_dir}" ]; then
        warn "mcp ${key}: source dir ${mod_dir} not found — skipped"
        return 0
    fi

    # Relocate the baked venv on first boot (mirrors the backend venv pattern).
    if [ ! -d "${venv}" ] && [ -d "${baked}" ]; then
        log "mcp ${key}: seeding venv from baked snapshot"
        cp -a "${baked}" "${venv}"
    fi

    ensure_mcp_module_deps "${key}" "${dir}" || return 0

    log "starting mcp ${key} (uvicorn --reload) on 0.0.0.0:${port} from ${dir}"
    (
        cd "${mod_dir}" || exit 1
        PYTHONPATH="${REPO_DIR}/druppie/mcp-servers:${mod_dir}" \
        MCP_PORT="${port}" \
        "${venv}/bin/python" -m uvicorn server:app \
            --host 0.0.0.0 --port "${port}" \
            --reload --reload-dir "${mod_dir}"
    ) >"${LOGS}/mcp-${key}.log" 2>&1 &
    PIDS="${PIDS} $!"
}

start_embedded_mcp_modules() {
    if [ -z "${EMBED_MODULES}" ]; then
        log "no embedded MCP modules (EMBED_MODULES empty)"
        return 0
    fi
    log "embedded MCP modules: ${EMBED_MODULES}"
    local key
    for key in ${EMBED_MODULES}; do
        start_mcp_module "${key}"
    done
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
    if ! command -v dbus-run-session >/dev/null 2>&1; then
        warn "dbus-run-session not in this image — desktop disabled (rebuild dev-workspace)"
        return 0
    fi

    log "starting desktop (XFCE over noVNC) — open /proxy/6080/ on the workspace host"
    # 127.0.0.1 only and -SecurityTypes None: the ONLY way in is code-server's
    # authenticated port proxy, same trust model as code-server's auth:none.
    Xvnc :1 -geometry "${DRUPPIE_DESKTOP_GEOMETRY:-1600x900}" -depth 24 \
        -SecurityTypes None -localhost -AlwaysShared -rfbport 5901 \
        >"${LOGS}/xvnc.log" 2>&1 &
    PIDS="${PIDS} $!"

    # Wait for the X server socket before starting clients, so the first XFCE
    # iteration doesn't fail with "xrdb: Can't open display ':1'".
    for _ in $(seq 1 50); do
        [ -S /tmp/.X11-unix/X1 ] && break
        sleep 0.1
    done

    # XDG_RUNTIME_DIR (/run/user/<uid>) is required by D-Bus and xfconfd; the
    # container starts without it, so create it once here.
    local uid; uid="$(id -u)"
    export XDG_RUNTIME_DIR="/run/user/${uid}"
    mkdir -p "${XDG_RUNTIME_DIR}" && chmod 700 "${XDG_RUNTIME_DIR}"

    # Respawn loop: an XFCE "Log out" (or session crash) restarts the session
    # instead of tearing down the pod via the wait -n below.
    #
    # dbus-run-session provides a private session bus that stays live for the
    # full duration of startxfce4. This replaces `dbus-launch
    # --exit-with-session`, whose bus exits prematurely in a container (no
    # controlling tty), leaving xfce4-session with a dead
    # DBUS_SESSION_BUS_ADDRESS — so xfconfd can't be activated and every XFCE
    # component pops "Unable to connect to settings server".
    (
        export DISPLAY=:1
        while :; do
            dbus-run-session -- startxfce4 >>"${LOGS}/xfce.log" 2>&1
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

# Claude Code: route through Azure AI Foundry using FOUNDRY_API_KEY (from
# envFrom). The Azure resource only deploys claude-opus-4-8, so all model
# aliases fall back to it. Override via env vars if the deployment changes.
if [ -n "${FOUNDRY_API_KEY:-}" ]; then
    export CLAUDE_CODE_USE_FOUNDRY=1
    export ANTHROPIC_FOUNDRY_API_KEY="${FOUNDRY_API_KEY}"
    export ANTHROPIC_FOUNDRY_RESOURCE="${ANTHROPIC_FOUNDRY_RESOURCE:-druppie-resource}"
    export ANTHROPIC_DEFAULT_SONNET_MODEL="${ANTHROPIC_DEFAULT_SONNET_MODEL:-claude-opus-4-8}"
    export ANTHROPIC_DEFAULT_HAIKU_MODEL="${ANTHROPIC_DEFAULT_HAIKU_MODEL:-claude-opus-4-8}"
    log "Claude Code configured for Azure AI Foundry (resource: ${ANTHROPIC_FOUNDRY_RESOURCE})"
fi

# opencode: auto-detects providers by env-var name (the names it looks for come
# from models.dev). The vault/envFrom keys use the druppie names, so export the
# opencode-recognized aliases as copies. The druppie names stay exported — the
# backend still reads ZAI_API_KEY / FOUNDRY_API_KEY (LLM_PROVIDER=zai/foundry).
#   ZAI_API_KEY    -> ZHIPU_API_KEY            (Z.AI + Z.AI Coding Plan share it)
#   FOUNDRY_API_KEY -> AZURE_API_KEY + AZURE_RESOURCE_NAME   (Azure / Foundry)
#
# Also persist the aliases to ~/.bashrc.d/opencode-env so desktop terminals
# (which are not direct children of this entrypoint) inherit them.
OPENCODE_BASHRC_D="${HOME}/.bashrc.d"
install -d -m 755 "${OPENCODE_BASHRC_D}"
# Ensure .bashrc sources .bashrc.d/ (idempotent — only adds once).
if ! grep -q 'source.*\.bashrc\.d' "${HOME}/.bashrc" 2>/dev/null; then
    printf '\nfor f in "${HOME}/.bashrc.d/"*; do [ -r "$f" ] && source "$f"; done\n' >> "${HOME}/.bashrc"
fi
OPENCODE_ENV_FILE="${OPENCODE_BASHRC_D}/opencode-env"
: > "${OPENCODE_ENV_FILE}"  # clear stale entries on restart

if [ -n "${ZAI_API_KEY:-}" ]; then
    export ZHIPU_API_KEY="${ZAI_API_KEY}"
    printf 'export ZHIPU_API_KEY="%s"\n' "${ZAI_API_KEY}" >> "${OPENCODE_ENV_FILE}"
fi
if [ -n "${FOUNDRY_API_KEY:-}" ]; then
    export AZURE_API_KEY="${FOUNDRY_API_KEY}"
    export AZURE_RESOURCE_NAME="${AZURE_RESOURCE_NAME:-${ANTHROPIC_FOUNDRY_RESOURCE:-druppie-resource}}"
    export ANTHROPIC_API_KEY="${FOUNDRY_API_KEY}"
    export ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL:-https://${AZURE_RESOURCE_NAME}.services.ai.azure.com/anthropic/v1}"
    # The only Claude model deployed on this Foundry resource is claude-opus-4-8.
    export OPENCODE_DEFAULT_MODEL="${OPENCODE_DEFAULT_MODEL:-anthropic:claude-opus-4-8}"
    log "opencode: Z.AI/Z.AI Coding Plan + Azure + Anthropic(via Foundry) providers available via env aliases (model: ${OPENCODE_DEFAULT_MODEL})"
    {
        printf 'export AZURE_API_KEY="%s"\n' "${FOUNDRY_API_KEY}"
        printf 'export AZURE_RESOURCE_NAME="%s"\n' "${AZURE_RESOURCE_NAME}"
        printf 'export ANTHROPIC_API_KEY="%s"\n' "${FOUNDRY_API_KEY}"
        printf 'export ANTHROPIC_BASE_URL="%s"\n' "${ANTHROPIC_BASE_URL}"
        printf 'export OPENCODE_DEFAULT_MODEL="%s"\n' "${OPENCODE_DEFAULT_MODEL}"
    } >> "${OPENCODE_ENV_FILE}"
fi

seed_workspace

# Keep the workspace's own runtime artifacts out of the Source Control pane:
# they are per-pod state, not repo changes. Repo-local ignore (info/exclude)
# so the repo's .gitignore stays untouched. After seed_workspace: that step
# creates .git on first boot.
printf '.seeded\n.logs/\n.dep-hashes/\n.venv/\n.venvs/\n.data/\n.claude/\n' \
    > "${REPO_DIR}/.git/info/exclude"

checkout_branch
configure_git
clone_side_repos
if [ "${RECOVERY_MODE:-}" != "true" ]; then
    ensure_frontend_deps
    ensure_backend_deps
else
    log "RECOVERY_MODE=true — skipping frontend/backend dep install"
fi

start_code_server
if [ "${RECOVERY_MODE:-}" != "true" ]; then
    start_backend
    start_frontend
    start_embedded_mcp_modules
else
    log "RECOVERY_MODE=true — skipping backend, frontend, and MCP modules"
fi
start_desktop

log "all services started (pids:${PIDS}) — tailing until a child exits or SIGTERM"

# Wait for the first child to exit, then tear the rest down so k8s restarts the
# pod. `wait -n` needs bash (provided by the image); this script runs under bash.
wait -n
warn "a child process exited — shutting down so the pod restarts"
terminate

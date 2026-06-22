# Deployment Guide

Complete guide for deploying Druppie with an external URL, nginx reverse proxy, TLS, and production configuration.

## Quick Reference

| Scenario | Command |
|----------|---------|
| Local development | `docker compose --profile dev --profile init up -d --build` |
| Production (first time) | See [Production Deployment](#production-deployment) below |
| Production (rebuild) | `docker compose --profile prod --profile init up -d --build` |
| Stop | `docker compose down` |
| Reset DB only | `docker compose --profile reset-db run --rm reset-db` |
| Full nuke | `docker compose --profile nuke run --rm nuke` |

## Architecture Overview

```
Internet → Nginx (443/HTTPS) → oauth2-proxy (auth gate) → Docker services
                                        ↓
                                  Keycloak (druppie-gate realm)

                         ┌─ Frontend (5273)
                         ├─ Backend API /api/ (8100)
                         ├─ WebSocket /ws/ (8100)
Nginx ──────────────────┼─ Keycloak /realms/* (8180)
                         └─ Gitea subdomain (3100)
```

### Service Map

| Service | Internal Port | Host Port (default) | URL Pattern |
|---------|--------------|---------------------|-------------|
| Frontend | 5173 | 5273 | `https://druppie.example.com/` |
| Backend API | 8000 | 8100 | `https://druppie.example.com/api/` |
| Keycloak | 8080 | 8180 | `https://druppie.example.com/realms/...` |
| Gitea | 3000 | 3100 | `https://git.example.com/` |
| PostgreSQL | 5432 | 5533 | Internal only |
| oauth2-proxy | 4180 | 127.0.0.1:4180 | Internal only |
| MCP Coding | 9001 | 9001 | Internal only |
| MCP Docker | 9002 | 9002 | Internal only |

### Two-Layer Auth

| Layer | Realm | Purpose | Login |
|-------|-------|---------|-------|
| 1 - Gate | `druppie-gate` | oauth2-proxy protects all endpoints via nginx `auth_request` | `druppie_team` / configured password |
| 2 - App | `druppie` | Backend JWT validation for RBAC (roles, approvals) | `admin` / `Admin123!` |

---

## Local Development (localhost)

```bash
cp .env.example .env
# Edit .env: set ZAI_API_KEY (required)
# Everything else has working defaults for localhost
docker compose --profile dev --profile init up -d --build
```

Access at `http://localhost:5273`.

---

## Production Deployment

### Prerequisites

- A Linux server with Docker and Docker Compose installed
- A domain name you control (e.g., `druppie.example.com`)
- Ability to create DNS records (A records or wildcard)
- Ports 80 and 443 open on your firewall

### Step 1: Choose Your URL Structure

You need **two subdomains**:

| Subdomain | Purpose | Example |
|-----------|---------|---------|
| `druppie.*` | Frontend + Backend + Keycloak | `druppie.example.com` |
| `git.*` (or `gitea.*`) | Gitea git server | `git.example.com` |

For this guide, we'll use:
- `druppie.example.com` - the main platform
- `git.example.com` - the git server

Replace `example.com` with your actual domain throughout.

### Step 2: Configure DNS

Create DNS records pointing to your server IP:

```
druppie.example.com    A    YOUR_SERVER_IP
git.example.com        A    YOUR_SERVER_IP
```

Or use a wildcard:

```
*.example.com    A    YOUR_SERVER_IP
```

Verify DNS propagation:

```bash
dig druppie.example.com +short
dig git.example.com +short
```

### Step 3: Obtain SSL Certificate

#### Option A: Certbot (Let's Encrypt) - Recommended

Install certbot:

```bash
sudo apt update && sudo apt install -y certbot
```

Obtain a wildcard certificate (covers both subdomains):

```bash
sudo certbot certonly --manual --preferred-challenges dns \
  -d '*.example.com' -d 'example.com'
```

This will ask you to create a DNS TXT record for verification. The certificates will be saved to:

```
/etc/letsencrypt/live/example.com/fullchain.pem
/etc/letsencrypt/live/example.com/privkey.pem
```

Set up auto-renewal:

```bash
sudo certbot renew --dry-run
# Certbot installs a systemd timer by default for auto-renewal
sudo systemctl list-timers | grep certbot
```

#### Option B: Existing Certificates

If you already have certificates, note the paths to:
- Full chain: `/path/to/fullchain.pem`
- Private key: `/path/to/privkey.pem`

### Step 4: Configure `.env`

```bash
cp .env.example .env
```

Edit `.env` with your production values:

```bash
# =============================================================================
# REQUIRED - Set these for your deployment
# =============================================================================

# Your external domain (used by all services)
EXTERNAL_HOST=druppie.example.com

# Druppie public domain (used by oauth2-proxy, Caddy, and security gate)
# This is the full hostname users will access in their browser
DRUPPIE_DOMAIN=druppie.example.com

# Public URLs (HTTPS, no port - nginx handles routing)
FRONTEND_PUBLIC_URL=https://druppie.example.com
BACKEND_PUBLIC_URL=https://druppie.example.com
KEYCLOAK_PUBLIC_URL=https://druppie.example.com
GITEA_PUBLIC_URL=https://git.example.com
CORS_ORIGINS=https://druppie.example.com

# Keycloak HTTPS
KC_HOSTNAME_STRICT_HTTPS=true

# =============================================================================
# SECURITY - Generate strong secrets
# =============================================================================

# Generate each with: python3 -c "import secrets; print(secrets.token_urlsafe(32))"
ENVIRONMENT=production
INTERNAL_API_KEY=<generate>
SANDBOX_API_SECRET=<generate>
DRUPPIE_MODULE_API_TOKEN=<generate>
OAUTH2_PROXY_CLIENT_SECRET=<generate>
OAUTH2_PROXY_COOKIE_SECRET=<generate>

# =============================================================================
# LLM PROVIDER
# =============================================================================

LLM_PROVIDER=zai
ZAI_API_KEY=your_api_key_here

# =============================================================================
# OPTIONAL - Multi-instance isolation
# =============================================================================

# If running alongside another Druppie instance on the same server:
# COMPOSE_PROJECT_NAME=druppie-prod
# PORT_OFFSET=2000
```

**Generating secrets** - run this for each secret:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

### Step 5: Apply Port Offset (if co-existing with dev instance)

If another Druppie instance runs on the same machine:

```bash
# In .env:
COMPOSE_PROJECT_NAME=druppie-prod
PORT_OFFSET=2000

# Apply:
bash scripts/apply-port-offset.sh
```

This shifts all ports by +2000. All Docker resources are isolated by `COMPOSE_PROJECT_NAME`.

### Step 6: Configure Nginx

#### Generate the config

```bash
# Generate nginx config from template
bash nginx/generate-config.sh \
  --druppie-domain druppie.example.com \
  --gitea-domain git.example.com \
  --ssl-cert-dir /etc/letsencrypt/live/example.com \
  --backend-port 8100 \
  --frontend-port 5273 \
  --keycloak-port 8180 \
  --gitea-port 3100
```

This generates `nginx/druppie-prod.conf` with your domain and port settings.

#### Install the config

```bash
# Copy to nginx sites-available
sudo cp nginx/druppie-prod.conf /etc/nginx/sites-available/druppie-prod

# Enable the site
sudo ln -sf /etc/nginx/sites-available/druppie-prod /etc/nginx/sites-enabled/

# Remove default site if present
sudo rm -f /etc/nginx/sites-enabled/default

# Test configuration
sudo nginx -t

# Reload nginx
sudo systemctl reload nginx
```

#### What the nginx config does

The generated config sets up:

1. **HTTP → HTTPS redirect** (port 80 → 443)
2. **TLS termination** with your SSL certificate
3. **Security headers** (HSTS, X-Frame-Options, X-Content-Type-Options)
4. **oauth2-proxy auth gate** - all protected routes check authentication via `auth_request`
5. **Keycloak endpoints** (`/realms/*`, `/resources/*`, `/protocol/*`) - NO auth gate (needed for login flow)
6. **Backend API** (`/api/*`, `/health`) - protected, proxied to backend
7. **WebSocket** (`/ws/*`) - protected, with upgrade headers
8. **Frontend** (catch-all `/`) - protected, proxied to frontend
9. **Gitea subdomain** - separate server block, protected

#### If not using oauth2-proxy

To disable the auth gate (not recommended for production), remove or comment out the `auth_request` and `error_page 401` lines in each location block.

### Step 7: Build and Start

```bash
docker compose --profile prod --profile init up -d --build
```

Monitor the startup:

```bash
# Watch container logs
docker compose logs -f

# Check all containers are healthy
docker compose ps
```

The init container runs automatically on first launch:
1. Creates the `druppie` Keycloak realm with roles and test users
2. Sets up the Gitea admin user and OAuth integration
3. Creates the `druppie-gate` security realm for oauth2-proxy

### Step 8: Verify

```bash
# Check container health
docker compose ps

# Test HTTPS access (should redirect to oauth2-proxy login)
curl -k https://druppie.example.com/health

# Test Gitea
curl -k https://git.example.com/

# Check Keycloak is reachable through nginx
curl -k https://druppie.example.com/realms/druppie/.well-known/openid-configuration
```

### Step 9: Login

1. Navigate to `https://druppie.example.com`
2. You'll be redirected to the oauth2-proxy gate login
   - Username: `druppie_team`
   - Password: the value you set in `GATE_PASSWORD` (see `.env`)
3. After gate authentication, you'll see the Druppie app login
4. Use Keycloak credentials:

| User | Password | Roles |
|------|----------|-------|
| admin | Admin123! | admin |
| architect | Architect123! | architect |
| developer | Developer123! | developer |
| analyst | Analyst123! | business_analyst |
| normal_user | User123! | user |

---

## How It Works

### Dynamic Resource Naming

All Docker resources are dynamically named via `COMPOSE_PROJECT_NAME`:

- **Containers**: `<PROJECT>-<service>-1` (e.g., `druppie-prod-backend-1`)
- **Volumes**: `<PROJECT>_<key>` (e.g., `druppie-prod_postgres`)
- **Networks**: `<PROJECT>_<key>` (e.g., `druppie-prod_main`)

For dev, `COMPOSE_PROJECT_NAME` defaults to the directory name. For prod, set it explicitly in `.env`.

### Dynamic URL Resolution

All public-facing URLs are controlled by environment variables:

| Variable | Default | Used By |
|----------|---------|---------|
| `FRONTEND_PUBLIC_URL` | `http://HOST:FRONTEND_PORT` | Keycloak redirect URIs, CORS |
| `BACKEND_PUBLIC_URL` | `http://HOST:BACKEND_PORT` | Frontend build args (VITE_API_URL) |
| `KEYCLOAK_PUBLIC_URL` | `http://HOST:KEYCLOAK_PORT` | Backend issuer URL, frontend build args |
| `GITEA_PUBLIC_URL` | `http://HOST:GITEA_PORT` | Keycloak redirect URIs, Gitea ROOT_URL |

- **For localhost dev**: leave them unset - defaults to `http://localhost:PORT`
- **For production**: set them to `https://your-domain` (no port) - reverse proxy handles routing

### Dynamic repo_url Resolution

The backend stores only `repo_name` and `repo_owner` in the database (not full URLs). The `repo_url` shown in the frontend is resolved dynamically from these fields plus the `GITEA_URL` env var. This means switching between dev and prod requires zero database changes.

### Keycloak Init

The `iac/users.yaml` file uses `${FRONTEND_PUBLIC_URL}` and `${GITEA_PUBLIC_URL}` as template variables. The `setup_keycloak.py` script substitutes them at init time. No manual editing needed.

### Security Gate (druppie-gate realm)

Production uses a **two-layer auth** architecture:

| Layer | Realm | Purpose |
|-------|-------|---------|
| 1 - Gate | `druppie-gate` | oauth2-proxy protects all endpoints via nginx `auth_request` |
| 2 - App | `druppie` | Backend JWT validation for RBAC (roles, approvals) |

The gate is configured by `scripts/setup_gate.py` which runs automatically during init. It creates:

- **Realm**: `druppie-gate` (isolated from the app realm)
- **Client**: `druppie-proxy` (used by oauth2-proxy, secret from `OAUTH2_PROXY_CLIENT_SECRET`)
- **User**: `druppie_team` (the shared team credential for the gate)

To re-run the gate setup manually (or after changing `DRUPPIE_DOMAIN`):

```bash
GATE_DOMAIN=druppie.example.com python3 scripts/setup_gate.py
docker compose --profile prod restart oauth2-proxy
```

---

## Switching Between Dev and Prod

Everything is controlled by `.env`. To switch:

```bash
# Dev mode (localhost, no HTTPS, default ports)
COMPOSE_PROJECT_NAME=druppie-dev
EXTERNAL_HOST=localhost
ENVIRONMENT=development
# Leave all PUBLIC_URL variables commented out

# Prod mode (reverse proxy, HTTPS)
COMPOSE_PROJECT_NAME=druppie-prod
EXTERNAL_HOST=druppie.example.com
ENVIRONMENT=production
FRONTEND_PUBLIC_URL=https://druppie.example.com
BACKEND_PUBLIC_URL=https://druppie.example.com
KEYCLOAK_PUBLIC_URL=https://druppie.example.com
GITEA_PUBLIC_URL=https://git.example.com
CORS_ORIGINS=https://druppie.example.com
KC_HOSTNAME_STRICT_HTTPS=true
```

Then rebuild: `docker compose --profile prod --profile init up -d --build`

No code changes needed. No database changes needed. Only `.env` differs between environments.

---

## Recovery

### Lost Keycloak Realms

If Keycloak data is lost (e.g., volume deleted, `docker compose down` with `-v`):

```bash
# 1. Remove the init marker so init re-runs
docker volume rm ${COMPOSE_PROJECT_NAME:-druppie}_init_marker

# 2. Rebuild with init profile
docker compose --profile prod --profile init up -d --build

# Or run individual setup scripts manually:
python3 scripts/setup_keycloak.py
python3 scripts/setup_gate.py
python3 scripts/setup_gitea.py
docker compose --profile prod restart oauth2-proxy
```

### Full Reset

```bash
# Reset application database only (preserves users)
docker compose --profile reset-db run --rm reset-db

# Hard reset (wipe all data + re-initialize)
docker compose --profile dev down
docker compose --profile infra --profile reset-hard run --rm reset-hard
docker compose --profile prod --profile init up -d --build

# Full nuke & rebuild (destroys everything including images)
docker compose --profile nuke run --rm nuke
```

---

## Troubleshooting

### Nginx won't start

```bash
# Check config syntax
sudo nginx -t

# Check if another process uses port 80/443
sudo ss -tlnp | grep -E ':80|:443'

# Check nginx error logs
sudo tail -f /var/log/nginx/error.log
```

### SSL certificate errors

```bash
# Verify certificate files exist
ls -la /etc/letsencrypt/live/example.com/

# Check certificate validity
sudo openssl x509 -in /etc/letsencrypt/live/example.com/fullchain.pem -noout -dates

# Check certificate covers your domain
sudo openssl x509 -in /etc/letsencrypt/live/example.com/fullchain.pem -noout -text | grep -A1 "Subject Alternative Name"
```

### Containers not healthy

```bash
# Check all container status
docker compose ps

# Check specific service logs
docker compose logs druppie-backend
docker compose logs keycloak
docker compose logs gitea

# Restart a specific service
docker compose restart druppie-backend
```

### oauth2-proxy login loop

```bash
# Check oauth2-proxy logs
docker compose logs oauth2-proxy

# Verify the gate realm exists
curl http://localhost:8180/realms/druppie-gate/.well-known/openid-configuration

# Re-run gate setup if needed
python3 scripts/setup_gate.py
docker compose restart oauth2-proxy
```

### CORS errors

Verify `CORS_ORIGINS` in `.env` matches your frontend URL exactly (including `https://`):
```bash
# In .env:
CORS_ORIGINS=https://druppie.example.com
```

Then rebuild the backend:
```bash
docker compose --profile prod up -d --build druppie-backend
```

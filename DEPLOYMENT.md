# Deployment Guide

## Quick Reference

| Scenario | Command |
|----------|---------|
| Local development | `docker compose --profile dev --profile init up -d --build` |
| Production (first time) | See [First-Time Production Setup](#first-time-production-setup) |
| Production (rebuild) | `docker compose --profile prod --profile init up -d --build` |
| Stop | `docker compose down` |
| Reset DB only | `docker compose --profile reset-db run --rm reset-db` |
| Full nuke | `docker compose --profile nuke run --rm nuke` |

## Environment Variables

### Minimal Setup (localhost dev)

```bash
cp .env.example .env
# Edit .env: set ZAI_API_KEY (required)
# Everything else has working defaults for localhost
docker compose --profile dev --profile init up -d --build
```

### Production with Reverse Proxy

Set these in `.env`:

```bash
EXTERNAL_HOST=druppie.example.com

# Public URLs — set these when behind a reverse proxy with TLS
# If unset, they default to http://EXTERNAL_HOST:PORT
FRONTEND_PUBLIC_URL=https://druppie.example.com
BACKEND_PUBLIC_URL=https://druppie.example.com
KEYCLOAK_PUBLIC_URL=https://druppie.example.com
GITEA_PUBLIC_URL=https://gitea.druppie.example.com
CORS_ORIGINS=https://druppie.example.com

# Keycloak HTTPS (set when behind reverse proxy)
KC_HOSTNAME_PORT=
KC_HOSTNAME_STRICT_HTTPS=true

# Production mode — requires non-default INTERNAL_API_KEY and SANDBOX_API_SECRET
ENVIRONMENT=production
INTERNAL_API_KEY=<generate with: python3 -c "import secrets; print(secrets.token_urlsafe(32))">
SANDBOX_API_SECRET=<generate with: python3 -c "import secrets; print(secrets.token_urlsafe(32))">
DRUPPIE_MODULE_API_TOKEN=<generate with: python3 -c "import secrets; print(secrets.token_urlsafe(32))">
```

### Multi-Instance (Running Alongside Another Druppie)

If another Druppie instance runs on the same machine, use port offsets to avoid collisions:

```bash
# In .env:
PORT_OFFSET=2000

# Then apply:
bash scripts/apply-port-offset.sh
```

This shifts all ports by +2000. Container names, volumes, and networks are isolated via `COMPOSE_PROJECT_NAME` (defaults to directory name).

## How It Works

### Dynamic URL Resolution

All public-facing URLs are controlled by 4 environment variables:

| Variable | Default | Used By |
|----------|---------|---------|
| `FRONTEND_PUBLIC_URL` | `http://HOST:FRONTEND_PORT` | Keycloak redirect URIs, CORS |
| `BACKEND_PUBLIC_URL` | `http://HOST:BACKEND_PORT` | Frontend build args (VITE_API_URL) |
| `KEYCLOAK_PUBLIC_URL` | `http://HOST:KEYCLOAK_PORT` | Backend issuer URL, frontend build args |
| `GITEA_PUBLIC_URL` | `http://HOST:GITEA_PORT` | Keycloak redirect URIs, backend CORS |

- **For localhost dev**: leave them unset — defaults to `http://localhost:PORT`
- **For production**: set them to `https://your-domain` (no port) — reverse proxy handles routing

### Keycloak Init (iac/users.yaml)

The `iac/users.yaml` file uses `${FRONTEND_PUBLIC_URL}` and `${GITEA_PUBLIC_URL}` as template variables. The `setup_keycloak.py` script substitutes them at init time. No manual editing needed.

## First-Time Production Setup

### 1. Prepare .env

```bash
cp .env.example .env
# Edit .env — set all variables from the "Production with Reverse Proxy" section above
```

### 2. Set Port Offset (if co-existing with another instance)

```bash
# In .env, set PORT_OFFSET=2000 (or any non-overlapping offset)
bash scripts/apply-port-offset.sh
```

### 3. Configure Nginx

```bash
# Generate htpasswd (Basic Auth)
sudo apt install apache2-utils  # if not installed
sudo htpasswd -c /etc/nginx/druppie-prod.htpasswd druppie_team
# Enter password when prompted

# Install nginx site config
sudo cp nginx/druppie-prod.conf /etc/nginx/sites-available/
sudo ln -s /etc/nginx/sites-available/druppie-prod.conf /etc/nginx/sites-enabled/

# Update the proxy_pass ports in the nginx config to match your PORT_OFFSET
# Backend: 10000 + offset, Frontend: 7173 + offset, Keycloak: 10080 + offset, Gitea: 5000 + offset

# Validate and reload
sudo nginx -t && sudo systemctl reload nginx
```

### 4. DNS

Point these DNS records to your server:

```
druppie.notitiemaker.nl      → A record → server IP
gitea.druppie.notitiemaker.nl → A record → server IP (wildcard *.notitiemaker.nl also works)
```

### 5. SSL Certificate

The nginx config expects certs at `/etc/letsencrypt/live/notitiemaker.nl/`. Obtain a wildcard cert:

```bash
sudo certbot certonly --manual --preferred-challenges dns -d '*.notitiemaker.nl' -d notitiemaker.nl
```

### 6. Build and Start

```bash
docker compose --profile prod --profile init up -d --build
```

### 7. Verify

```bash
# Check all containers are healthy
docker compose ps

# Test HTTPS access
curl -u druppie_team:YOUR_PASSWORD https://druppie.notitiemaker.nl/health
```

## Switching Between Dev and Prod

Everything is controlled by `.env`. To switch:

```bash
# Dev mode (localhost, no HTTPS, default ports)
EXTERNAL_HOST=localhost
ENVIRONMENT=development
# Leave all PUBLIC_URL variables commented out

# Prod mode (reverse proxy, HTTPS)
EXTERNAL_HOST=druppie.notitiemaker.nl
ENVIRONMENT=production
FRONTEND_PUBLIC_URL=https://druppie.notitiemaker.nl
BACKEND_PUBLIC_URL=https://druppie.notitiemaker.nl
KEYCLOAK_PUBLIC_URL=https://druppie.notitiemaker.nl
GITEA_PUBLIC_URL=https://gitea.druppie.notitiemaker.nl
CORS_ORIGINS=https://druppie.notitiemaker.nl
KC_HOSTNAME_PORT=
KC_HOSTNAME_STRICT_HTTPS=true
```

Then rebuild: `docker compose --profile prod --profile init up -d --build`

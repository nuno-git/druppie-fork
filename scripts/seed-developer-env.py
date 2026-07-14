#!/usr/bin/env python3
"""Seed a developer environment's Vault secrets (mirror of main/colab-dev shape).

Creates druppie/developers/<user>/{database,keycloak,gitea,app,workspace} under
the ai-team-k8s KV v2 mount, mirroring how main/colab-dev are organized — so a
developer dev-workspace owns its own credentials.

- Reuses druppie/colab-dev/app for shared LLM-key defaults (override per user
  in the Vault UI afterwards).
- Generates per-env random passwords for database/keycloak/gitea.
- Copies the shared oauth2-proxy client/cookie secret from branch-env/workspace-oauth.

Requires: a Vault token with write access to ai-team-k8s/*. Vault is reached
through the WSL->corporate relay (http://127.0.0.1:8888) by default.

Usage:
    VAULT_TOKEN=hvs.x env -u NO_PROXY -u no_proxy \
        python3 scripts/seed-developer-env.py robbe
    # optional: --instance druppie-dev-robbe  (sets the DB host in database.url)
"""
import argparse, json, os, secrets, ssl, sys, urllib.request

VAULT = os.environ.get("VAULT_ADDR", "https://aivault.waterschap.org")
MOUNT = "ai-team-k8s"
PROXY_URL = os.environ.get("VAULT_PROXY", "http://127.0.0.1:8888")


def opener():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False                       # Waterschap internal CA
    ctx.verify_mode = ssl.CERT_NONE
    handlers = [urllib.request.HTTPSHandler(context=ctx)]
    if PROXY_URL:
        handlers.append(urllib.request.ProxyHandler({"http": PROXY_URL, "https": PROXY_URL}))
    return urllib.request.build_opener(*handlers)


def req(opener, token, method, path, body=None):
    url = f"{VAULT}/v1/{MOUNT}/data/{path}"
    data = json.dumps({"data": body}).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method, headers={"X-Vault-Token": token})
    if body is not None:
        r.add_header("Content-Type", "application/json")
    try:
        with opener.open(r, timeout=20) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        return {"_error": f"{e.code}: {e.read().decode()[:160]}"}


def read(opener, token, path):
    d = req(opener, token, "GET", path)
    return (d.get("data") or {}).get("data") or {}


def write(opener, token, path, data):
    return "_error" not in req(opener, token, "POST", path, data)


def rand(n=24):
    return secrets.token_urlsafe(n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("user", help="developer username (Vault path developers/<user>)")
    ap.add_argument("--instance", default=None,
                    help="env instance name (default druppie-dev-<user>); sets the DB host in database.url")
    args = ap.parse_args()

    token = os.environ.get("VAULT_TOKEN")
    if not token:
        sys.exit("VAULT_TOKEN env var is required")
    op = opener()
    user = args.user
    instance = args.instance or f"druppie-dev-{user}"

    defaults = read(op, token, "druppie/colab-dev/app")
    ws = read(op, token, "branch-env/workspace-oauth")
    client_secret = ws.get("client-secret") or rand(48)
    cookie_secret = ws.get("cookie-secret") or rand(32)

    llm = ["zai-api-key", "deepseek-api-key", "deepinfra-api-key",
           "foundry-api-key", "openrouter-api-key"]
    app = {k: defaults.get(k) or rand(20) for k in llm}
    app.update({"internal-api-key": rand(32), "module-api-token": rand(32),
                "sandbox-api-secret": rand(32)})

    db_pw = rand(18)
    paths = {
        "database":  {"password": db_pw,
                      "url": f"postgresql://druppie:{db_pw}@{instance}-druppie-db:5432/druppie"},
        "keycloak":  {"admin-user": "admin", "admin-password": rand(16), "db-password": rand(16)},
        "gitea":     {"admin-password": rand(16), "db-password": rand(16),
                      "password": rand(16), "token": rand(20)},
        "app":       app,
        "workspace": {"client-secret": client_secret, "cookie-secret": cookie_secret},
    }
    for sub, data in paths.items():
        p = f"druppie/developers/{user}/{sub}"
        ok = write(op, token, p, data)
        print(f"  {'OK ' if ok else 'FAIL'} {p}  keys={list(data.keys())}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Setup script for the druppie-gate Keycloak realm.

This creates the "security gate" — a separate Keycloak realm used by
oauth2-proxy to protect all production endpoints. Users must authenticate
against this realm first (the "gate") before reaching the app itself
(which uses the main 'druppie' realm for RBAC).

Two-layer auth:
  Layer 1: druppie-gate realm → oauth2-proxy → nginx auth_request
  Layer 2: druppie realm → backend JWT validation (RBAC/roles)

This script is idempotent — safe to run multiple times.

Usage:
  # From project root (after Keycloak is healthy):
  python3 scripts/setup_gate.py

  # Or with custom settings:
  KEYCLOAK_URL=http://localhost:10080 \
  KEYCLOAK_ADMIN=admin \
  KEYCLOAK_ADMIN_PASSWORD=kc-admin-N8rF2pL5xQ9w \
  OAUTH2_PROXY_CLIENT_SECRET=tqHSSTX1ECvxkd5VRkeLbgtJa807RVHD \
  GATE_DOMAIN=druppie.notitiemaker.nl \
  python3 scripts/setup_gate.py
"""

import json
import os
import sys
import requests


class KeycloakAdmin:
    """Minimal Keycloak Admin API client."""

    def __init__(self, base_url: str, admin_user: str, admin_password: str):
        self.base_url = base_url.rstrip("/")
        self.admin_user = admin_user
        self.admin_password = admin_password
        self.token = None
        self._authenticate()

    def _authenticate(self):
        url = f"{self.base_url}/realms/master/protocol/openid-connect/token"
        resp = requests.post(url, data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": self.admin_user,
            "password": self.admin_password,
        })
        resp.raise_for_status()
        self.token = resp.json()["access_token"]

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def get(self, path):
        resp = requests.get(f"{self.base_url}/admin{path}", headers=self._headers())
        resp.raise_for_status()
        return resp.json() if resp.text else None

    def post(self, path, data):
        resp = requests.post(
            f"{self.base_url}/admin{path}",
            headers=self._headers(),
            json=data,
        )
        return resp

    def put(self, path, data):
        resp = requests.put(
            f"{self.base_url}/admin{path}",
            headers=self._headers(),
            json=data,
        )
        return resp


def ensure_realm(kc: KeycloakAdmin, realm_name: str) -> bool:
    """Create realm if it doesn't exist. Returns True if created."""
    resp = kc.post("/realms", {
        "realm": realm_name,
        "enabled": True,
        "displayName": "Druppie Security Gate",
        "sslRequired": "external",
        "registrationAllowed": False,
        "loginWithEmailAllowed": True,
        "duplicateEmailsAllowed": False,
        "resetPasswordAllowed": False,
        "editUsernameAllowed": False,
        "bruteForceProtected": True,
        "permanentLockout": False,
        "maxFailureWaitSeconds": 900,
        "minimumQuickLoginWaitSeconds": 60,
        "waitIncrementSeconds": 60,
        "quickLoginCheckMilliSeconds": 1000,
        "maxDeltaTimeSeconds": 43200,
        "failureFactor": 5,
        "accessTokenLifespan": 43200,  # 12 hours
        "ssoSessionMaxLifespan": 43200,
    })
    if resp.status_code == 201:
        print(f"  [OK] Created realm '{realm_name}'")
        return True
    elif resp.status_code == 409:
        print(f"  [OK] Realm '{realm_name}' already exists")
        return False
    else:
        print(f"  [ERROR] Failed to create realm: {resp.status_code} {resp.text}")
        sys.exit(1)


def ensure_client(kc: KeycloakAdmin, realm: str, client_id: str, client_secret: str, domain: str):
    """Create or update the oauth2-proxy client."""
    redirect_uri = f"https://{domain}/oauth2/callback"
    web_origin = f"https://{domain}"

    client_data = {
        "clientId": client_id,
        "enabled": True,
        "clientAuthenticatorType": "client-secret",
        "secret": client_secret,
        "redirectUris": [redirect_uri],
        "webOrigins": [web_origin, "+"],
        "standardFlowEnabled": True,
        "directAccessGrantsEnabled": True,
        "serviceAccountsEnabled": False,
        "publicClient": False,
        "protocol": "openid-connect",
        "fullScopeAllowed": True,
        "attributes": {
            "pkce.code.challenge.method": "S256",
            "oauth2.device.authorization.grant.enabled": "false",
            "backchannel.logout.session.required": "true",
            "backchannel.logout.revoke.offline.tokens": "false",
        },
    }

    # Check if client exists
    existing = kc.get(f"/realms/{realm}/clients?clientId={client_id}")
    if existing:
        client_uuid = existing[0]["id"]
        resp = kc.put(f"/realms/{realm}/clients/{client_uuid}", client_data)
        if resp.status_code in (200, 204):
            print(f"  [OK] Updated client '{client_id}'")
        else:
            print(f"  [WARN] Failed to update client: {resp.status_code} {resp.text}")
    else:
        resp = kc.post(f"/realms/{realm}/clients", client_data)
        if resp.status_code == 201:
            print(f"  [OK] Created client '{client_id}'")
        else:
            print(f"  [ERROR] Failed to create client: {resp.status_code} {resp.text}")
            sys.exit(1)


def ensure_user(kc: KeycloakAdmin, realm: str, username: str, password: str):
    """Create user if it doesn't exist."""
    existing = kc.get(f"/realms/{realm}/users?username={username}")
    if existing:
        print(f"  [OK] User '{username}' already exists")
        return

    resp = kc.post(f"/realms/{realm}/users", {
        "username": username,
        "enabled": True,
        "emailVerified": True,
        "email": f"{username}@druppie.local",
        "credentials": [{
            "type": "password",
            "value": password,
            "temporary": False,
        }],
    })
    if resp.status_code == 201:
        print(f"  [OK] Created user '{username}'")
    else:
        print(f"  [ERROR] Failed to create user: {resp.status_code} {resp.text}")
        sys.exit(1)


def main():
    # Configuration from env vars (with defaults from .env)
    keycloak_url = os.getenv("KEYCLOAK_URL", "http://localhost:10080")
    admin_user = os.getenv("KEYCLOAK_ADMIN", "admin")
    admin_password = os.getenv("KEYCLOAK_ADMIN_PASSWORD", "kc-admin-N8rF2pL5xQ9w")
    client_secret = os.getenv("OAUTH2_PROXY_CLIENT_SECRET", "tqHSSTX1ECvxkd5VRkeLbgtJa807RVHD")
    domain = os.getenv("GATE_DOMAIN", "druppie.notitiemaker.nl")

    gate_realm = "druppie-gate"
    gate_client = "druppie-proxy"
    gate_user = "druppie_team"
    gate_password = "Druppie2026!SecureGate"

    print("=" * 50)
    print("  Druppie Security Gate Setup")
    print("=" * 50)
    print(f"  Keycloak:     {keycloak_url}")
    print(f"  Gate realm:   {gate_realm}")
    print(f"  Gate client:  {gate_client}")
    print(f"  Gate domain:  {domain}")
    print(f"  Gate user:    {gate_user}")
    print()

    kc = KeycloakAdmin(keycloak_url, admin_user, admin_password)

    print("[1/3] Setting up realm")
    ensure_realm(kc, gate_realm)

    print("[2/3] Setting up oauth2-proxy client")
    ensure_client(kc, gate_realm, gate_client, client_secret, domain)

    print("[3/3] Setting up gate user")
    ensure_user(kc, gate_realm, gate_user, gate_password)

    print()
    print("=" * 50)
    print("  Security Gate setup complete!")
    print("=" * 50)
    print()
    print(f"  Gate login:   {gate_user} / {'*' * len(gate_password)}")
    print(f"  App login:    admin / Admin123! (in 'druppie' realm)")
    print()
    print("  Restart oauth2-proxy to pick up changes:")
    print(f"    docker compose --profile prod restart oauth2-proxy")


if __name__ == "__main__":
    main()

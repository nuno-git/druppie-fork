#!/usr/bin/env python3
"""
Setup script for the druppie-gate Keycloak realm (security gate for oauth2-proxy).

Two-layer auth:
  Layer 1: druppie-gate realm -> oauth2-proxy -> nginx auth_request
  Layer 2: druppie realm -> backend JWT validation (RBAC/roles)

Idempotent - safe to run multiple times.

Usage:
  python3 scripts/setup_gate.py
  GATE_DOMAIN=druppie.example.com python3 scripts/setup_gate.py
"""

import json
import os
import sys
import requests


class KeycloakAdmin:
    def __init__(self, base_url: str, admin_user: str, admin_password: str):
        self.base_url = base_url.rstrip("/")
        self.token = None
        resp = requests.post(f"{self.base_url}/realms/master/protocol/openid-connect/token", data={
            "grant_type": "password", "client_id": "admin-cli",
            "username": admin_user, "password": admin_password,
        })
        resp.raise_for_status()
        self.token = resp.json()["access_token"]

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    def get(self, path):
        r = requests.get(f"{self.base_url}/admin{path}", headers=self._headers())
        r.raise_for_status()
        return r.json() if r.text else None

    def post(self, path, data):
        return requests.post(f"{self.base_url}/admin{path}", headers=self._headers(), json=data)

    def put(self, path, data):
        return requests.put(f"{self.base_url}/admin{path}", headers=self._headers(), json=data)


def ensure_realm(kc: KeycloakAdmin, realm_name: str):
    resp = kc.post("/realms", {
        "realm": realm_name, "enabled": True, "displayName": "Druppie Security Gate",
        "sslRequired": "external", "registrationAllowed": False,
        "loginWithEmailAllowed": True, "duplicateEmailsAllowed": False,
        "resetPasswordAllowed": False, "editUsernameAllowed": False,
        "bruteForceProtected": True, "permanentLockout": False,
        "maxFailureWaitSeconds": 900, "minimumQuickLoginWaitSeconds": 60,
        "waitIncrementSeconds": 60, "quickLoginCheckMilliSeconds": 1000,
        "maxDeltaTimeSeconds": 43200, "failureFactor": 5,
        "accessTokenLifespan": 43200, "ssoSessionMaxLifespan": 43200,
    })
    if resp.status_code == 201:
        print(f"  [OK] Created realm '{realm_name}'")
    elif resp.status_code == 409:
        print(f"  [OK] Realm '{realm_name}' already exists")
    else:
        print(f"  [ERROR] {resp.status_code} {resp.text}"); sys.exit(1)


def ensure_client(kc: KeycloakAdmin, realm: str, client_id: str, client_secret: str, domain: str):
    client_data = {
        "clientId": client_id, "enabled": True,
        "clientAuthenticatorType": "client-secret", "secret": client_secret,
        "redirectUris": [f"https://{domain}/oauth2/callback"],
        "webOrigins": [f"https://{domain}", "+"],
        "standardFlowEnabled": True, "directAccessGrantsEnabled": True,
        "serviceAccountsEnabled": False, "publicClient": False,
        "protocol": "openid-connect", "fullScopeAllowed": True,
        "attributes": {
            "pkce.code.challenge.method": "",
            "oauth2.device.authorization.grant.enabled": "false",
            "backchannel.logout.session.required": "true",
            "backchannel.logout.revoke.offline.tokens": "false",
        },
    }
    existing = kc.get(f"/realms/{realm}/clients?clientId={client_id}")
    if existing:
        uuid = existing[0]["id"]
        client_data["id"] = uuid
        r = kc.put(f"/realms/{realm}/clients/{uuid}", client_data)
        print(f"  [OK] Updated client '{client_id}'")
        ensure_audience_mapper(kc, realm, uuid)
    else:
        r = kc.post(f"/realms/{realm}/clients", client_data)
        if r.status_code == 201:
            print(f"  [OK] Created client '{client_id}'")
            new = kc.get(f"/realms/{realm}/clients?clientId={client_id}")
            ensure_audience_mapper(kc, realm, new[0]["id"])
        else:
            print(f"  [ERROR] {r.status_code} {r.text}"); sys.exit(1)


def ensure_audience_mapper(kc: KeycloakAdmin, realm: str, client_uuid: str):
    mappers = kc.get(f"/realms/{realm}/clients/{client_uuid}/protocol-mappers/models")
    if any(m["name"] == "audience-mapper" for m in (mappers or [])):
        print("  [OK] Audience mapper already exists")
        return
    r = kc.post(f"/realms/{realm}/clients/{client_uuid}/protocol-mappers/add-models", [{
        "name": "audience-mapper", "protocol": "openid-connect",
        "protocolMapper": "oidc-audience-mapper", "consentRequired": False,
        "config": {
            "included.client.audience": "druppie-proxy",
            "id.token.claim": "false", "access.token.claim": "true",
            "userinfo.token.claim": "false",
        },
    }])
    print(f"  [OK] Added audience mapper" if r.status_code in (200, 201, 204) else f"  [WARN] Audience mapper: {r.status_code}")


def ensure_platform_access_role(kc: KeycloakAdmin, realm: str):
    r = kc.post(f"/realms/{realm}/roles", {
        "name": "platform-access",
        "description": "Access to the Druppie platform via oauth2-proxy",
    })
    if r.status_code == 201:
        print("  [OK] Created role 'platform-access'")
    elif r.status_code == 409:
        print("  [OK] Role 'platform-access' already exists")
    else:
        print(f"  [WARN] Role creation: {r.status_code} {r.text}")


def ensure_user(kc: KeycloakAdmin, realm: str, username: str, password: str, role: str):
    existing = kc.get(f"/realms/{realm}/users?username={username}")
    if existing:
        user_uuid = existing[0]["id"]
        print(f"  [OK] User '{username}' already exists")
    else:
        r = kc.post(f"/realms/{realm}/users", {
            "username": username, "enabled": True, "emailVerified": True,
            "email": f"{username}@druppie.local",
            "credentials": [{"type": "password", "value": password, "temporary": False}],
        })
        if r.status_code == 201:
            print(f"  [OK] Created user '{username}'")
            user_uuid = r.headers.get("Location", "").split("/")[-1]
        else:
            print(f"  [ERROR] {r.status_code} {r.text}"); sys.exit(1)
            return

    # Assign platform-access role
    role_data = kc.get(f"/realms/{realm}/roles/{role}")
    if role_data and "id" in role_data:
        kc.post(f"/realms/{realm}/users/{user_uuid}/role-mappings/realm", [role_data])
        print(f"  [OK] Assigned '{role}' role to '{username}'")

    # Ensure client has roles scope as default
    client = kc.get(f"/realms/{realm}/clients?clientId=druppie-proxy")
    if client:
        client_uuid = client[0]["id"]
        roles_scope = kc.get(f"/realms/{realm}/client-scopes?search=roles")
        if roles_scope:
            kc.put(f"/realms/{realm}/clients/{client_uuid}/default-client-scopes/{roles_scope[0]['id']}", {})
            # Also add role to client scope-mappings
            kc.post(f"/realms/{realm}/clients/{client_uuid}/scope-mappings/realm", [role_data])


def main():
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

    print("[1/5] Setting up realm")
    ensure_realm(kc, gate_realm)

    print("[2/5] Setting up oauth2-proxy client")
    ensure_client(kc, gate_realm, gate_client, client_secret, domain)

    print("[3/5] Setting up platform-access role")
    ensure_platform_access_role(kc, gate_realm)

    print("[4/5] Setting up gate user")
    ensure_user(kc, gate_realm, gate_user, gate_password, "platform-access")

    print("[5/5] Done")
    print()
    print(f"  Gate login:   {gate_user} / {'*' * len(gate_password)}")
    print(f"  App login:    admin / Admin123! (in 'druppie' realm)")
    print()
    print("  Restart oauth2-proxy:")
    print(f"    docker compose --profile prod restart oauth2-proxy")


if __name__ == "__main__":
    main()

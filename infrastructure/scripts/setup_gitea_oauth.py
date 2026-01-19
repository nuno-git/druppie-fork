#!/usr/bin/env python3
"""
Gitea OAuth2 Setup Script for Keycloak Integration

This script configures Gitea to use Keycloak as an OAuth2/OpenID Connect provider.
"""

import os
import sys
import time
import requests

# Configuration
GITEA_URL = os.getenv("GITEA_URL", "http://localhost:3000")
GITEA_ADMIN_USER = os.getenv("GITEA_ADMIN_USER", "gitea_admin")
GITEA_ADMIN_PASSWORD = os.getenv("GITEA_ADMIN_PASSWORD", "Gitea123!")
GITEA_ADMIN_EMAIL = os.getenv("GITEA_ADMIN_EMAIL", "gitea@druppie.local")

KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://localhost:8080")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "druppie")
KEYCLOAK_ADMIN = os.getenv("KEYCLOAK_ADMIN", "admin")
KEYCLOAK_ADMIN_PASSWORD = os.getenv("KEYCLOAK_ADMIN_PASSWORD", "admin_password")


def wait_for_gitea():
    """Wait for Gitea to be ready."""
    print("[INFO] Waiting for Gitea...")
    for attempt in range(30):
        try:
            response = requests.get(f"{GITEA_URL}/api/v1/version", timeout=5)
            if response.status_code == 200:
                print(f"[OK] Gitea is ready: {response.json()}")
                return True
        except Exception:
            pass
        print(f"  Waiting... ({attempt + 1}/30)")
        time.sleep(2)
    return False


def create_gitea_admin():
    """Create Gitea admin user if not exists."""
    print("\n[STEP 1] Creating Gitea admin user...")

    # Try to create user via Gitea API (initial setup)
    url = f"{GITEA_URL}/api/v1/admin/users"

    # First, try to login to check if admin exists
    session = requests.Session()

    # Check if we can login with admin
    try:
        login_url = f"{GITEA_URL}/user/login"
        response = session.get(login_url)

        # If we get redirected to install, Gitea needs initial setup
        if "install" in response.url:
            print("[INFO] Gitea needs initial setup - please complete setup via web UI first")
            print(f"       Visit: {GITEA_URL}/install")
            return None
    except Exception as e:
        print(f"[WARN] Could not check Gitea status: {e}")

    # Try to get a token for the admin user
    token_url = f"{GITEA_URL}/api/v1/users/{GITEA_ADMIN_USER}/tokens"
    auth = (GITEA_ADMIN_USER, GITEA_ADMIN_PASSWORD)

    try:
        # Check if admin user exists and can authenticate
        response = requests.get(f"{GITEA_URL}/api/v1/user", auth=auth, timeout=10)
        if response.status_code == 200:
            print(f"[OK] Admin user '{GITEA_ADMIN_USER}' exists and can authenticate")
            return auth
        elif response.status_code == 401:
            print(f"[INFO] Admin user may not exist or wrong password")
    except Exception as e:
        print(f"[WARN] Error checking admin user: {e}")

    return None


def get_keycloak_client_secret():
    """Get Gitea client secret from Keycloak."""
    print("\n[STEP 2] Getting Keycloak client secret for Gitea...")

    # Authenticate with Keycloak admin
    token_url = f"{KEYCLOAK_URL}/realms/master/protocol/openid-connect/token"
    data = {
        "grant_type": "password",
        "client_id": "admin-cli",
        "username": KEYCLOAK_ADMIN,
        "password": KEYCLOAK_ADMIN_PASSWORD,
    }

    try:
        response = requests.post(token_url, data=data, timeout=10)
        response.raise_for_status()
        token = response.json()["access_token"]
        print("[OK] Authenticated with Keycloak")
    except Exception as e:
        print(f"[ERROR] Failed to authenticate with Keycloak: {e}")
        return None

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # Get Gitea client
    clients_url = f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/clients"
    response = requests.get(clients_url, headers=headers, params={"clientId": "gitea"})

    if response.status_code != 200:
        print(f"[ERROR] Failed to get clients: {response.text}")
        return None

    clients = response.json()
    if not clients:
        print("[ERROR] Gitea client not found in Keycloak")
        return None

    client_id = clients[0]["id"]

    # Get client secret
    secret_url = f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/clients/{client_id}/client-secret"
    response = requests.get(secret_url, headers=headers)

    if response.status_code == 200:
        secret = response.json().get("value")
        if secret:
            print(f"[OK] Got Gitea client secret")
            return secret

    # Generate new secret if none exists
    response = requests.post(secret_url, headers=headers)
    if response.status_code == 200:
        secret = response.json().get("value")
        print(f"[OK] Generated new Gitea client secret")
        return secret

    print(f"[ERROR] Failed to get/generate client secret: {response.text}")
    return None


def configure_gitea_oauth(auth, client_secret):
    """Configure Gitea OAuth2 authentication source."""
    print("\n[STEP 3] Configuring Gitea OAuth2 authentication source...")

    if not auth:
        print("[SKIP] No admin auth available, skipping OAuth2 setup")
        print("[INFO] Please configure OAuth2 manually in Gitea admin panel:")
        print(f"       {GITEA_URL}/admin/auths/new")
        print(f"       Type: OAuth2")
        print(f"       OAuth2 Provider: OpenID Connect")
        print(f"       Client ID: gitea")
        print(f"       Client Secret: {client_secret}")
        print(f"       Discovery URL: {KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/.well-known/openid-configuration")
        return

    # Check existing auth sources
    auth_url = f"{GITEA_URL}/api/v1/admin/auths"

    try:
        response = requests.get(auth_url, auth=auth, timeout=10)
        if response.status_code == 200:
            auths = response.json()
            for a in auths:
                if a.get("name") == "Keycloak":
                    print("[OK] Keycloak auth source already exists")
                    return
    except Exception as e:
        print(f"[WARN] Could not check existing auth sources: {e}")

    # Create OAuth2 authentication source
    auth_data = {
        "type": 6,  # OAuth2
        "name": "Keycloak",
        "is_active": True,
        "oauth2_config": {
            "provider": "openidConnect",
            "client_id": "gitea",
            "client_secret": client_secret,
            "open_id_connect_auto_discovery_url": f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/.well-known/openid-configuration",
            "scopes": ["openid", "profile", "email"],
        },
    }

    try:
        response = requests.post(auth_url, json=auth_data, auth=auth, timeout=10)
        if response.status_code == 201:
            print("[OK] Created Keycloak OAuth2 authentication source")
        elif response.status_code == 422:
            print("[WARN] Auth source may already exist or invalid config")
            print(f"       Response: {response.text}")
        else:
            print(f"[ERROR] Failed to create auth source: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"[ERROR] Failed to configure OAuth2: {e}")


def main():
    print("=" * 60)
    print("Druppie - Gitea OAuth2 Setup for Keycloak")
    print("=" * 60)

    if not wait_for_gitea():
        print("[ERROR] Gitea is not available")
        sys.exit(1)

    auth = create_gitea_admin()
    client_secret = get_keycloak_client_secret()

    if client_secret:
        configure_gitea_oauth(auth, client_secret)

    print("\n" + "=" * 60)
    print("[INFO] To login to Gitea with Keycloak:")
    print(f"       1. Visit {GITEA_URL}")
    print("       2. Click 'Sign in with Keycloak'")
    print("       3. Use your Keycloak credentials (e.g., admin/Admin123!)")
    print("=" * 60)


if __name__ == "__main__":
    main()

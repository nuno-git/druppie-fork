#!/usr/bin/env python3
"""
Gitea Setup Script for Druppie Governance Platform

This script:
1. Creates an admin user in Gitea
2. Configures OAuth2 integration with Keycloak
3. Creates default organization and repository
"""

import os
import sys
import time
import requests

# Configuration
GITEA_URL = os.getenv("GITEA_URL", "http://localhost:3000")
GITEA_ADMIN_USER = os.getenv("GITEA_ADMIN_USER", "druppie-admin")
GITEA_ADMIN_PASSWORD = os.getenv("GITEA_ADMIN_PASSWORD", "admin123")
GITEA_ADMIN_EMAIL = os.getenv("GITEA_ADMIN_EMAIL", "admin@druppie.local")

KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://localhost:8080")
KEYCLOAK_REALM = "druppie"
GITEA_CLIENT_SECRET = os.getenv("GITEA_CLIENT_SECRET", "")

EXTERNAL_HOST = os.getenv("EXTERNAL_HOST", "localhost")


def wait_for_gitea():
    """Wait for Gitea to be ready."""
    print("[INFO] Waiting for Gitea to be ready...")

    for attempt in range(30):
        try:
            response = requests.get(f"{GITEA_URL}/api/v1/version", timeout=5)
            if response.status_code == 200:
                version = response.json().get("version", "unknown")
                print(f"[OK] Gitea is ready (version: {version})")
                return True
        except Exception:
            pass

        print(f"[WAIT] Gitea not ready yet... ({attempt + 1}/30)")
        time.sleep(5)

    print("[ERROR] Gitea did not become ready")
    return False


def create_admin_user():
    """Create admin user using Gitea CLI inside container."""
    print("\n[STEP 1] Creating admin user...")

    import subprocess

    # Check if user exists first
    try:
        result = subprocess.run(
            [
                "docker",
                "exec",
                "druppie-gitea",
                "gitea",
                "admin",
                "user",
                "list",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if GITEA_ADMIN_USER in result.stdout:
            print(f"  [OK] Admin user '{GITEA_ADMIN_USER}' already exists")
            return True

    except Exception as e:
        print(f"  [WARN] Could not check existing users: {e}")

    # Create admin user
    try:
        result = subprocess.run(
            [
                "docker",
                "exec",
                "druppie-gitea",
                "gitea",
                "admin",
                "user",
                "create",
                "--username",
                GITEA_ADMIN_USER,
                "--password",
                GITEA_ADMIN_PASSWORD,
                "--email",
                GITEA_ADMIN_EMAIL,
                "--admin",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            print(f"  [OK] Created admin user '{GITEA_ADMIN_USER}'")
            return True
        else:
            if "already exists" in result.stderr.lower() or "already exists" in result.stdout.lower():
                print(f"  [OK] Admin user '{GITEA_ADMIN_USER}' already exists")
                return True
            print(f"  [ERROR] Failed to create admin user: {result.stderr}")
            return False

    except Exception as e:
        print(f"  [ERROR] Failed to create admin user: {e}")
        return False


def get_admin_token():
    """Get or create admin access token."""
    print("\n[STEP 2] Getting admin access token...")

    # Try to create a new token
    session = requests.Session()

    # Login first to get session
    login_url = f"{GITEA_URL}/user/login"
    response = session.get(login_url)

    # Extract CSRF token from form
    import re

    csrf_match = re.search(r'name="_csrf"\s+value="([^"]+)"', response.text)
    if not csrf_match:
        print("  [WARN] Could not find CSRF token")
        return None

    csrf_token = csrf_match.group(1)

    # Login
    login_data = {
        "_csrf": csrf_token,
        "user_name": GITEA_ADMIN_USER,
        "password": GITEA_ADMIN_PASSWORD,
    }

    response = session.post(login_url, data=login_data, allow_redirects=False)

    if response.status_code not in [200, 302, 303]:
        print(f"  [WARN] Login failed: {response.status_code}")
        return None

    # Create access token via API
    token_url = f"{GITEA_URL}/api/v1/users/{GITEA_ADMIN_USER}/tokens"

    # Get new CSRF token after login
    settings_response = session.get(f"{GITEA_URL}/user/settings/applications")
    csrf_match = re.search(r'name="_csrf"\s+value="([^"]+)"', settings_response.text)

    if csrf_match:
        csrf_token = csrf_match.group(1)

    # Use basic auth for token creation
    auth = (GITEA_ADMIN_USER, GITEA_ADMIN_PASSWORD)

    token_data = {
        "name": "druppie-setup-token",
        "scopes": ["write:admin", "write:organization", "write:repository", "write:user"],
    }

    response = requests.post(token_url, json=token_data, auth=auth)

    if response.status_code == 201:
        token = response.json().get("sha1", "")
        print(f"  [OK] Created access token")
        return token
    elif response.status_code == 422:  # Token already exists
        print(f"  [INFO] Token already exists, trying to use basic auth")
        return None
    else:
        print(f"  [WARN] Could not create token: {response.status_code}")
        return None


def configure_oauth2(token: str = None):
    """Configure Keycloak OAuth2 provider."""
    print("\n[STEP 3] Configuring OAuth2 with Keycloak...")

    if not GITEA_CLIENT_SECRET:
        print("  [WARN] GITEA_CLIENT_SECRET not set, skipping OAuth2 configuration")
        return

    # Use basic auth if no token
    auth = (GITEA_ADMIN_USER, GITEA_ADMIN_PASSWORD) if not token else None
    headers = {"Authorization": f"token {token}"} if token else {}

    # Check existing OAuth2 sources
    sources_url = f"{GITEA_URL}/api/v1/admin/auths"
    response = requests.get(sources_url, auth=auth, headers=headers)

    if response.status_code == 200:
        for source in response.json():
            if source.get("name") == "keycloak":
                print("  [OK] Keycloak OAuth2 already configured")
                return

    # Configure OAuth2
    oauth2_config = {
        "type": 6,  # OAuth2
        "name": "keycloak",
        "is_active": True,
        "oauth2_config": {
            "provider": "openidConnect",
            "client_id": "gitea",
            "client_secret": GITEA_CLIENT_SECRET,
            "open_id_connect_auto_discovery_url": f"http://{EXTERNAL_HOST}:8080/realms/{KEYCLOAK_REALM}/.well-known/openid-configuration",
            "icon_url": "",
        },
    }

    response = requests.post(sources_url, json=oauth2_config, auth=auth, headers=headers)

    if response.status_code in [200, 201]:
        print("  [OK] Configured Keycloak OAuth2")
    else:
        print(f"  [WARN] Could not configure OAuth2: {response.status_code} - {response.text}")


def create_organization(token: str = None):
    """Create default Druppie organization."""
    print("\n[STEP 4] Creating default organization...")

    auth = (GITEA_ADMIN_USER, GITEA_ADMIN_PASSWORD) if not token else None
    headers = {"Authorization": f"token {token}"} if token else {}

    org_url = f"{GITEA_URL}/api/v1/orgs"

    # Check if org exists
    response = requests.get(f"{org_url}/druppie", auth=auth, headers=headers)
    if response.status_code == 200:
        print("  [OK] Organization 'druppie' already exists")
        return

    # Create organization
    org_data = {
        "username": "druppie",
        "full_name": "Druppie Governance",
        "description": "Druppie Governance Platform projects",
        "visibility": "public",
    }

    response = requests.post(org_url, json=org_data, auth=auth, headers=headers)

    if response.status_code == 201:
        print("  [OK] Created organization 'druppie'")
    elif response.status_code == 422:
        print("  [OK] Organization 'druppie' already exists")
    else:
        print(f"  [WARN] Could not create organization: {response.status_code}")


def create_sample_repo(token: str = None):
    """Create sample repository."""
    print("\n[STEP 5] Creating sample repository...")

    auth = (GITEA_ADMIN_USER, GITEA_ADMIN_PASSWORD) if not token else None
    headers = {"Authorization": f"token {token}"} if token else {}

    repo_url = f"{GITEA_URL}/api/v1/orgs/druppie/repos"

    # Check if repo exists
    response = requests.get(f"{GITEA_URL}/api/v1/repos/druppie/sample-project", auth=auth, headers=headers)
    if response.status_code == 200:
        print("  [OK] Repository 'sample-project' already exists")
        return

    # Create repository
    repo_data = {
        "name": "sample-project",
        "description": "Sample project for Druppie governance",
        "private": False,
        "auto_init": True,
        "readme": "Default",
    }

    response = requests.post(repo_url, json=repo_data, auth=auth, headers=headers)

    if response.status_code == 201:
        print("  [OK] Created repository 'sample-project'")
    elif response.status_code == 409:
        print("  [OK] Repository 'sample-project' already exists")
    else:
        print(f"  [WARN] Could not create repository: {response.status_code}")


def main():
    print("=" * 60)
    print("Druppie - Gitea Setup")
    print("=" * 60)

    if not wait_for_gitea():
        sys.exit(1)

    create_admin_user()
    token = get_admin_token()
    configure_oauth2(token)
    create_organization(token)
    create_sample_repo(token)

    print("\n" + "=" * 60)
    print("[DONE] Gitea setup complete!")
    print(f"  URL: http://{EXTERNAL_HOST}:3000")
    print(f"  Admin: {GITEA_ADMIN_USER} / {GITEA_ADMIN_PASSWORD}")
    print("=" * 60)


if __name__ == "__main__":
    main()

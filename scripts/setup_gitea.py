#!/usr/bin/env python
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
import subprocess
import requests

# Configuration
GITEA_URL = os.getenv("GITEA_URL", "http://localhost:3000")
GITEA_ADMIN_USER = os.getenv("GITEA_ADMIN_USER", "gitea_admin")
GITEA_ADMIN_PASSWORD = os.getenv("GITEA_ADMIN_PASSWORD", "GiteaAdmin123")
GITEA_ADMIN_EMAIL = os.getenv("GITEA_ADMIN_EMAIL", "gitea@druppie.local")

KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://localhost:8080")
KEYCLOAK_INTERNAL_URL = os.getenv("KEYCLOAK_INTERNAL_URL", "http://keycloak:8080")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "druppie")
KEYCLOAK_ADMIN = os.getenv("KEYCLOAK_ADMIN", "admin")
KEYCLOAK_ADMIN_PASSWORD = os.getenv("KEYCLOAK_ADMIN_PASSWORD", "admin_password")

EXTERNAL_HOST = os.getenv("EXTERNAL_HOST", "localhost")

# .env file path (project root, or override via ENV_FILE env var for Docker)
ENV_FILE = os.getenv("ENV_FILE", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))


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


def run_gitea_cli(args: list) -> tuple[bool, str, str]:
    """Run Gitea CLI command inside container as git user."""
    try:
        result = subprocess.run(
            ["docker", "exec", "-u", "git", "druppie-new-gitea", "gitea"] + args,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode == 0, result.stdout, result.stderr
    except Exception as e:
        return False, "", str(e)


def create_admin_user():
    """Create admin user using Gitea CLI inside container."""
    print("\n[STEP 1] Creating admin user...")

    # Check if user exists first
    success, stdout, stderr = run_gitea_cli(["admin", "user", "list"])

    if success and GITEA_ADMIN_USER in stdout:
        print(f"  [OK] Admin user '{GITEA_ADMIN_USER}' already exists")
        return True

    # Create admin user
    success, stdout, stderr = run_gitea_cli([
        "admin", "user", "create",
        "--username", GITEA_ADMIN_USER,
        "--password", GITEA_ADMIN_PASSWORD,
        "--email", GITEA_ADMIN_EMAIL,
        "--admin",
    ])

    if success:
        print(f"  [OK] Created admin user '{GITEA_ADMIN_USER}'")
        return True
    elif "already exists" in stderr.lower() or "already exists" in stdout.lower():
        print(f"  [OK] Admin user '{GITEA_ADMIN_USER}' already exists")
        return True
    else:
        print(f"  [ERROR] Failed to create admin user: {stderr}")
        return False


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
        print("  [OK] Authenticated with Keycloak")
    except Exception as e:
        print(f"  [ERROR] Failed to authenticate with Keycloak: {e}")
        return None

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # Get Gitea client
    clients_url = f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/clients"
    response = requests.get(clients_url, headers=headers, params={"clientId": "gitea"})

    if response.status_code != 200:
        print(f"  [ERROR] Failed to get clients: {response.text}")
        return None

    clients = response.json()
    if not clients:
        print("  [ERROR] Gitea client not found in Keycloak")
        return None

    client_id = clients[0]["id"]

    # Get client secret
    secret_url = f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/clients/{client_id}/client-secret"
    response = requests.get(secret_url, headers=headers)

    if response.status_code == 200:
        secret = response.json().get("value")
        if secret:
            print(f"  [OK] Got Gitea client secret")
            return secret

    # Generate new secret if none exists
    response = requests.post(secret_url, headers=headers)
    if response.status_code == 200:
        secret = response.json().get("value")
        print(f"  [OK] Generated new Gitea client secret")
        return secret

    print(f"  [ERROR] Failed to get/generate client secret: {response.text}")
    return None


def configure_oauth2(client_secret: str):
    """Configure Keycloak OAuth2 provider using Gitea CLI."""
    print("\n[STEP 3] Configuring OAuth2 with Keycloak...")

    if not client_secret:
        print("  [SKIP] No client secret available")
        return False

    # Check if OAuth source already exists
    success, stdout, stderr = run_gitea_cli(["admin", "auth", "list"])

    if success and "Keycloak" in stdout:
        print("  [OK] Keycloak OAuth2 already configured")
        return True

    # Add OAuth2 source using CLI
    # Use internal Docker URL for server-to-server communication
    discovery_url = f"{KEYCLOAK_INTERNAL_URL}/realms/{KEYCLOAK_REALM}/.well-known/openid-configuration"

    success, stdout, stderr = run_gitea_cli([
        "admin", "auth", "add-oauth",
        "--name", "Keycloak",
        "--provider", "openidConnect",
        "--key", "gitea",
        "--secret", client_secret,
        "--auto-discover-url", discovery_url,
        "--scopes", "openid profile email",
    ])

    if success:
        print("  [OK] Configured Keycloak OAuth2")
        return True
    elif "already exists" in stderr.lower():
        print("  [OK] Keycloak OAuth2 already configured")
        return True
    else:
        print(f"  [ERROR] Failed to configure OAuth2: {stderr}")
        return False


def create_organization():
    """Create default Druppie organization."""
    print("\n[STEP 4] Creating default organization...")

    # Use a session for proper auth handling
    session = requests.Session()
    session.auth = (GITEA_ADMIN_USER, GITEA_ADMIN_PASSWORD)
    session.headers.update({"Content-Type": "application/json"})

    org_url = f"{GITEA_URL}/api/v1/orgs"

    # Check if org exists
    try:
        response = session.get(f"{org_url}/druppie", timeout=10)
        if response.status_code == 200:
            print("  [OK] Organization 'druppie' already exists")
            return True
    except Exception as e:
        print(f"  [DEBUG] Check failed: {e}")

    # Create organization
    org_data = {
        "username": "druppie",
        "full_name": "Druppie Governance",
        "description": "Druppie Governance Platform projects",
        "visibility": "public",
    }

    try:
        response = session.post(org_url, json=org_data, timeout=10)

        if response.status_code == 201:
            print("  [OK] Created organization 'druppie'")
            return True
        elif response.status_code in [409, 422]:
            print("  [OK] Organization 'druppie' already exists")
            return True
        else:
            print(f"  [WARN] Could not create organization: {response.status_code} - {response.text[:100]}")
            return False
    except Exception as e:
        print(f"  [WARN] Could not create organization: {e}")
        return False


def update_env_token(token: str):
    """Update GITEA_TOKEN in the .env file, or append it if missing."""
    if not os.path.exists(ENV_FILE):
        with open(ENV_FILE, "a") as f:
            f.write(f"\n# Gitea Token for MCP services (git push)\nGITEA_TOKEN={token}\n")
        print(f"  [OK] Added GITEA_TOKEN to {ENV_FILE}")
        return

    with open(ENV_FILE, "r") as f:
        content = f.read()

    import re
    if re.search(r"^GITEA_TOKEN=", content, re.MULTILINE):
        content = re.sub(r"^GITEA_TOKEN=.*$", f"GITEA_TOKEN={token}", content, flags=re.MULTILINE)
        print(f"  [OK] Updated GITEA_TOKEN in {ENV_FILE}")
    else:
        content = content.rstrip("\n") + f"\n\n# Gitea Token for MCP services (git push)\nGITEA_TOKEN={token}\n"
        print(f"  [OK] Added GITEA_TOKEN to {ENV_FILE}")

    with open(ENV_FILE, "w") as f:
        f.write(content)


def create_access_token() -> str | None:
    """Create an access token for the admin user and return it."""
    print("\n[STEP 5] Creating access token for MCP services...")

    # Use a session for proper auth handling
    session = requests.Session()
    session.auth = (GITEA_ADMIN_USER, GITEA_ADMIN_PASSWORD)
    session.headers.update({"Content-Type": "application/json"})

    # List existing tokens
    tokens_url = f"{GITEA_URL}/api/v1/users/{GITEA_ADMIN_USER}/tokens"

    try:
        response = session.get(tokens_url, timeout=10)
        if response.status_code == 200:
            existing_tokens = response.json()
            # Check if our token already exists
            for token in existing_tokens:
                if token.get("name") == "druppie-mcp":
                    print("  [OK] Token 'druppie-mcp' already exists")
                    print("  [NOTE] Cannot retrieve existing token value - create a new one if needed")
                    return None
    except Exception as e:
        print(f"  [DEBUG] Failed to list tokens: {e}")

    # Create new access token
    token_data = {
        "name": "druppie-mcp",
        "scopes": ["write:repository", "write:user", "read:organization"]
    }

    try:
        response = session.post(tokens_url, json=token_data, timeout=10)

        if response.status_code == 201:
            token = response.json().get("sha1")
            print(f"  [OK] Created access token 'druppie-mcp'")
            update_env_token(token)
            return token
        elif response.status_code == 422:
            print("  [OK] Token 'druppie-mcp' already exists")
            return None
        else:
            print(f"  [WARN] Could not create token: {response.status_code} - {response.text[:100]}")
            return None
    except Exception as e:
        print(f"  [WARN] Could not create token: {e}")
        return None


def create_keycloak_users_in_gitea():
    """Create Gitea accounts for all Keycloak users from iac/users.yaml.

    This ensures OAuth auto-linking works: when a Keycloak user logs into
    Gitea for the first time, their account is automatically linked by email.
    Also allows the seed system to create repos under real users.
    """
    print("\n[STEP 6] Creating Gitea accounts for Keycloak users...")

    users_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "iac", "users.yaml")
    if not os.path.exists(users_file):
        print(f"  [SKIP] {users_file} not found")
        return

    import yaml
    with open(users_file) as f:
        config = yaml.safe_load(f) or {}

    users = config.get("users", [])
    if not users:
        print("  [SKIP] No users defined in iac/users.yaml")
        return

    session = requests.Session()
    session.auth = (GITEA_ADMIN_USER, GITEA_ADMIN_PASSWORD)
    session.headers.update({"Content-Type": "application/json"})

    created = 0
    for user in users:
        username = user["username"]
        email = user.get("email", f"{username}@druppie.local")
        password = user.get("password", "ChangeMe123!")

        # Check if user already exists
        try:
            r = session.get(f"{GITEA_URL}/api/v1/users/{username}", timeout=10)
            if r.status_code == 200:
                print(f"  [OK] User '{username}' already exists")
                continue
        except Exception:
            pass

        # Create the user via admin API
        user_data = {
            "username": username,
            "email": email,
            "password": password,
            "must_change_password": False,
            "login_name": username,
            "source_id": 0,
        }

        try:
            r = session.post(f"{GITEA_URL}/api/v1/admin/users", json=user_data, timeout=10)
            if r.status_code == 201:
                print(f"  [OK] Created Gitea user '{username}'")
                created += 1
            elif r.status_code in (409, 422):
                print(f"  [OK] User '{username}' already exists")
            else:
                print(f"  [WARN] Could not create user '{username}': {r.status_code} - {r.text[:100]}")
        except Exception as e:
            print(f"  [WARN] Could not create user '{username}': {e}")

    print(f"  [DONE] {created} new Gitea users created")


def create_sample_repo():
    """Create sample repository."""
    print("\n[STEP 7] Creating sample repository...")

    # Use a session for proper auth handling
    session = requests.Session()
    session.auth = (GITEA_ADMIN_USER, GITEA_ADMIN_PASSWORD)
    session.headers.update({"Content-Type": "application/json"})

    # Check if repo exists
    try:
        response = session.get(
            f"{GITEA_URL}/api/v1/repos/druppie/sample-project",
            timeout=10
        )
        if response.status_code == 200:
            print("  [OK] Repository 'sample-project' already exists")
            return True
    except Exception as e:
        print(f"  [DEBUG] Check failed: {e}")

    # Create repository
    repo_url = f"{GITEA_URL}/api/v1/orgs/druppie/repos"
    repo_data = {
        "name": "sample-project",
        "description": "Sample project for Druppie governance",
        "private": False,
        "auto_init": True,
        "readme": "Default",
    }

    try:
        response = session.post(repo_url, json=repo_data, timeout=10)

        if response.status_code == 201:
            print("  [OK] Created repository 'sample-project'")
            return True
        elif response.status_code in [409, 422]:
            print("  [OK] Repository 'sample-project' already exists")
            return True
        else:
            print(f"  [WARN] Could not create repository: {response.status_code} - {response.text[:100]}")
            return False
    except Exception as e:
        print(f"  [WARN] Could not create repository: {e}")
        return False


def main():
    print("=" * 60)
    print("Druppie - Gitea Setup")
    print("=" * 60)

    if not wait_for_gitea():
        sys.exit(1)

    create_admin_user()
    client_secret = get_keycloak_client_secret()
    configure_oauth2(client_secret)
    create_organization()
    token = create_access_token()
    create_keycloak_users_in_gitea()
    create_sample_repo()

    print("\n" + "=" * 60)
    print("[DONE] Gitea setup complete!")
    print(f"  URL: {GITEA_URL}")
    print(f"  Admin: {GITEA_ADMIN_USER} / {GITEA_ADMIN_PASSWORD}")
    print("")
    if token:
        print(f"  GITEA_TOKEN written to {ENV_FILE}")
        print("")
    else:
        print("  NOTE: If GITEA_TOKEN is not set in .env, commits won't be pushed.")
        print("    You may need to manually create a token in Gitea settings.")
        print("")
    print("  To login with Keycloak:")
    print("    1. Click 'Sign in with Keycloak'")
    print("    2. Use your Keycloak credentials (e.g., admin/Admin123!)")
    print("=" * 60)


if __name__ == "__main__":
    main()

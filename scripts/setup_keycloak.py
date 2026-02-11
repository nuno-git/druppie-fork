#!/usr/bin/env python
"""
Keycloak Setup Script for Druppie Governance Platform

This script:
1. Creates the 'druppie' realm
2. Creates roles (admin, developer, architect, infra-engineer, etc.)
3. Creates users with appropriate roles
4. Configures OAuth2 clients
"""

import os
import sys
import time
import requests
import yaml
from pathlib import Path

# Configuration
KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://localhost:8080")
ADMIN_USER = os.getenv("KEYCLOAK_ADMIN", "admin")
ADMIN_PASSWORD = os.getenv("KEYCLOAK_ADMIN_PASSWORD", "admin_password")
REALM_NAME = "druppie"

# Paths
SCRIPT_DIR = Path(__file__).parent.parent
IAC_DIR = SCRIPT_DIR / "iac"
USERS_FILE = IAC_DIR / "users.yaml"
REALM_FILE = IAC_DIR / "realm.yaml"


class KeycloakAdmin:
    """Simple Keycloak Admin API client."""

    def __init__(self, base_url: str, admin_user: str, admin_password: str):
        self.base_url = base_url.rstrip("/")
        self.admin_user = admin_user
        self.admin_password = admin_password
        self.token = None
        self._authenticate()

    def _authenticate(self):
        """Get admin access token."""
        url = f"{self.base_url}/realms/master/protocol/openid-connect/token"
        data = {
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": self.admin_user,
            "password": self.admin_password,
        }

        for attempt in range(10):
            try:
                response = requests.post(url, data=data, timeout=10)
                response.raise_for_status()
                self.token = response.json()["access_token"]
                print(f"[OK] Authenticated with Keycloak")
                return
            except Exception as e:
                print(f"[WAIT] Waiting for Keycloak... ({attempt + 1}/10)")
                time.sleep(5)

        raise Exception("Failed to authenticate with Keycloak")

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def create_realm(self, realm_name: str, config: dict = None):
        """Create a new realm."""
        url = f"{self.base_url}/admin/realms"

        realm_data = {
            "realm": realm_name,
            "enabled": True,
            "displayName": config.get("displayName", realm_name) if config else realm_name,
            "registrationAllowed": False,
            "resetPasswordAllowed": True,
            "rememberMe": True,
            "loginWithEmailAllowed": True,
        }

        if config:
            realm_data.update({k: v for k, v in config.items() if k not in ["roles", "clients", "clientScopes"]})

        response = requests.post(url, json=realm_data, headers=self._headers())

        if response.status_code == 409:
            print(f"[OK] Realm '{realm_name}' already exists")
            return True
        elif response.status_code == 201:
            print(f"[OK] Created realm '{realm_name}'")
            return True
        else:
            print(f"[ERROR] Failed to create realm: {response.text}")
            return False

    def create_role(self, realm: str, role_name: str, description: str = ""):
        """Create a realm role."""
        url = f"{self.base_url}/admin/realms/{realm}/roles"
        role_data = {"name": role_name, "description": description}

        response = requests.post(url, json=role_data, headers=self._headers())

        if response.status_code == 409:
            print(f"  [OK] Role '{role_name}' already exists")
        elif response.status_code == 201:
            print(f"  [OK] Created role '{role_name}'")
        else:
            print(f"  [ERROR] Failed to create role '{role_name}': {response.text}")

    def create_user(
        self,
        realm: str,
        username: str,
        email: str,
        first_name: str,
        last_name: str,
        password: str,
        roles: list = None,
    ):
        """Create a user with roles."""
        url = f"{self.base_url}/admin/realms/{realm}/users"

        user_data = {
            "username": username,
            "email": email,
            "firstName": first_name,
            "lastName": last_name,
            "enabled": True,
            "emailVerified": True,
            "credentials": [{"type": "password", "value": password, "temporary": False}],
        }

        response = requests.post(url, json=user_data, headers=self._headers())

        if response.status_code == 409:
            print(f"  [OK] User '{username}' already exists")
            # Get user ID for role assignment
            user_id = self._get_user_id(realm, username)
        elif response.status_code == 201:
            print(f"  [OK] Created user '{username}'")
            # Get user ID from Location header
            location = response.headers.get("Location", "")
            user_id = location.split("/")[-1] if location else self._get_user_id(realm, username)
        else:
            print(f"  [ERROR] Failed to create user '{username}': {response.text}")
            return

        # Assign roles
        if roles and user_id:
            self._assign_roles(realm, user_id, roles)

    def _get_user_id(self, realm: str, username: str) -> str:
        """Get user ID by username."""
        url = f"{self.base_url}/admin/realms/{realm}/users"
        response = requests.get(url, params={"username": username}, headers=self._headers())

        if response.status_code == 200:
            users = response.json()
            for user in users:
                if user.get("username") == username:
                    return user["id"]
        return None

    def _assign_roles(self, realm: str, user_id: str, role_names: list):
        """Assign realm roles to a user."""
        # Get available roles
        url = f"{self.base_url}/admin/realms/{realm}/roles"
        response = requests.get(url, headers=self._headers())

        if response.status_code != 200:
            return

        available_roles = {r["name"]: r for r in response.json()}

        # Build role mappings
        roles_to_assign = []
        for role_name in role_names:
            if role_name in available_roles:
                roles_to_assign.append(available_roles[role_name])

        if not roles_to_assign:
            return

        # Assign roles
        url = f"{self.base_url}/admin/realms/{realm}/users/{user_id}/role-mappings/realm"
        response = requests.post(url, json=roles_to_assign, headers=self._headers())

        if response.status_code in [200, 204]:
            print(f"    [OK] Assigned roles: {role_names}")
        else:
            print(f"    [WARN] Could not assign roles: {response.text}")

    def create_client(self, realm: str, client_config: dict):
        """Create an OAuth2 client."""
        url = f"{self.base_url}/admin/realms/{realm}/clients"

        response = requests.post(url, json=client_config, headers=self._headers())

        client_id = client_config.get("clientId", "unknown")

        if response.status_code == 409:
            print(f"  [OK] Client '{client_id}' already exists")
        elif response.status_code == 201:
            print(f"  [OK] Created client '{client_id}'")
        else:
            print(f"  [ERROR] Failed to create client '{client_id}': {response.text}")


def load_yaml(file_path: Path) -> dict:
    """Load YAML configuration file."""
    if not file_path.exists():
        print(f"[WARN] Config file not found: {file_path}")
        return {}

    with open(file_path) as f:
        return yaml.safe_load(f) or {}


def main():
    print("=" * 60)
    print("Druppie - Keycloak Setup")
    print("=" * 60)

    # Load configurations
    users_config = load_yaml(USERS_FILE)
    realm_config = load_yaml(REALM_FILE)

    # Initialize Keycloak admin client
    try:
        kc = KeycloakAdmin(KEYCLOAK_URL, ADMIN_USER, ADMIN_PASSWORD)
    except Exception as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    # Create realm
    print("\n[STEP 1] Creating realm...")
    if not kc.create_realm(REALM_NAME, realm_config):
        sys.exit(1)

    # Create roles
    print("\n[STEP 2] Creating roles...")
    roles = users_config.get("roles", [])
    for role in roles:
        kc.create_role(REALM_NAME, role["name"], role.get("description", ""))

    # Create users
    print("\n[STEP 3] Creating users...")
    default_password = users_config.get("defaultPassword", "changeme123")
    users = users_config.get("users", [])

    for user in users:
        kc.create_user(
            realm=REALM_NAME,
            username=user["username"],
            email=user.get("email", f"{user['username']}@druppie.local"),
            first_name=user.get("firstName", user["username"]),
            last_name=user.get("lastName", "User"),
            password=user.get("password", default_password),
            roles=user.get("realmRoles", []),
        )

    # Create clients
    print("\n[STEP 4] Creating OAuth2 clients...")
    clients = users_config.get("clients", [])

    external_host = os.getenv("EXTERNAL_HOST", "localhost")

    # Environment variable substitutions for dynamic port configuration
    env_substitutions = {
        "${EXTERNAL_HOST}": external_host,
        "${FRONTEND_PORT}": os.getenv("FRONTEND_PORT", "5273"),
        "${KEYCLOAK_PORT}": os.getenv("KEYCLOAK_PORT", "8180"),
        "${GITEA_PORT}": os.getenv("GITEA_PORT", "3100"),
        "${GITEA_SSH_PORT}": os.getenv("GITEA_SSH_PORT", "2223"),
        "${BACKEND_PORT}": os.getenv("BACKEND_PORT", "8100"),
    }

    def substitute_env(value: str) -> str:
        for placeholder, replacement in env_substitutions.items():
            value = value.replace(placeholder, replacement)
        return value

    for client in clients:
        # Replace environment variables in URIs
        if "redirectUris" in client:
            client["redirectUris"] = [substitute_env(uri) for uri in client["redirectUris"]]
        if "webOrigins" in client:
            client["webOrigins"] = [substitute_env(uri) for uri in client["webOrigins"]]
        if "rootUrl" in client:
            client["rootUrl"] = substitute_env(client["rootUrl"])

        kc.create_client(REALM_NAME, client)

    print("\n" + "=" * 60)
    print("[DONE] Keycloak setup complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()

"""Guacamole HTTP Client.

Provides an async HTTP client for the Apache Guacamole REST API, used to
provision remote-access connections (RDP/SSH/VNC) and grant per-user READ
permissions on them.

This is a core service client (like ``gitea.py``), NOT an MCP server. It is
intended to be called internally by services that manage remote desktop
provisioning. Auth uses the token model: ``login()`` obtains an ``authToken``
which is cached on the instance and injected as ``?token=`` on every
subsequent request.

Structure mirrors ``druppie/core/gitea.py``: module-level env config, a fresh
``httpx.AsyncClient`` per request via ``_new_client()``, a uniform ``_request``
wrapper returning ``{success, status_code, data/error}``, and a stateless
factory ``get_guacamole_client()``.
"""

import os
from typing import Any

import httpx
import structlog

logger = structlog.get_logger()

GUACAMOLE_URL = os.getenv("GUACAMOLE_URL", "http://guacamole:8080")
GUACAMOLE_ADMIN_USER = os.getenv("GUACAMOLE_ADMIN_USER", "guacadmin")
GUACAMOLE_ADMIN_PASSWORD = os.getenv("GUACAMOLE_ADMIN_PASSWORD", "guacadmin")

# Security warning for default credentials
if GUACAMOLE_ADMIN_PASSWORD == "guacadmin":
    logger.warning(
        "guacamole_default_password",
        message=(
            "GUACAMOLE_ADMIN_PASSWORD is the default 'guacadmin' - change it "
            "in production. Guacamole provisioning will still work in dev."
        ),
    )


class GuacamoleClient:
    """Async HTTP client for the Apache Guacamole REST API.

    All non-login requests are authenticated via an ``authToken`` query
    parameter. The token is obtained lazily on the first authenticated
    request (see ``_ensure_token``) and cached for the lifetime of the
    instance. Because ``get_guacamole_client()`` returns a fresh instance
    each call, there is no shared mutable token state across consumers.

    The JDBC (PostgreSQL) data source is assumed; ``_datasource`` controls
    the ``/session/data/{datasource}/...`` path segment.
    """

    def __init__(self):
        self.base_url = GUACAMOLE_URL
        self.username = GUACAMOLE_ADMIN_USER
        self.password = GUACAMOLE_ADMIN_PASSWORD
        self._token: str | None = None
        self._datasource = "postgresql"

    async def close(self):
        """Close the HTTP client. No-op with per-request clients."""
        pass

    def _new_client(self) -> httpx.AsyncClient:
        """Return a fresh AsyncClient for a single request.

        No auth is baked in here: Guacamole authenticates each request with a
        ``?token=`` query parameter, which is injected by ``_request``.
        """
        return httpx.AsyncClient(
            base_url=self.base_url,
            timeout=30.0,
        )

    @staticmethod
    def _as_list(data: Any) -> list:
        """Normalize a Guacamole collection response to a list.

        Guacamole's REST API returns collections inconsistently across
        versions/endpoints - some as JSON arrays, others as object maps keyed
        by identifier. Treat both forms uniformly.
        """
        if data is None:
            return []
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return list(data.values())
        return []

    async def login(self) -> dict[str, Any]:
        """Authenticate against Guacamole and cache the auth token.

        POSTs form-encoded credentials to ``/guacamole/api/tokens``. On
        success the ``authToken`` from the response is stored on the instance
        and used for all subsequent requests.

        Returns:
            Uniform result dict with ``success``, ``status_code``, and either
            ``data`` or ``error``.
        """
        async with self._new_client() as client:
            try:
                response = await client.post(
                    "/guacamole/api/tokens",
                    data={
                        "username": self.username,
                        "password": self.password,
                    },
                )

                result: dict[str, Any] = {
                    "success": response.status_code in (200, 201, 204),
                    "status_code": response.status_code,
                }

                if response.text:
                    try:
                        result["data"] = response.json()
                    except ValueError:
                        result["data"] = response.text

                if result["success"]:
                    data = result.get("data")
                    token = data.get("authToken") if isinstance(data, dict) else None
                    if not token:
                        result["success"] = False
                        result["error"] = "Guacamole login response missing authToken"
                        logger.warning("guacamole_login_no_token", status=response.status_code)
                    else:
                        self._token = token
                        logger.info("guacamole_login_success", username=self.username)
                else:
                    logger.warning(
                        "guacamole_login_failed",
                        username=self.username,
                        status=response.status_code,
                        response=result.get("data"),
                    )

                return result

            except httpx.RequestError as e:
                logger.error(
                    "guacamole_login_request_error",
                    error=str(e),
                    exc_info=True,
                )
                return {
                    "success": False,
                    "error": str(e),
                }

    async def _ensure_token(self) -> str:
        """Return a valid auth token, logging in if necessary.

        Raises:
            RuntimeError: if login has not yet succeeded and cannot be
                performed now.
        """
        if self._token:
            return self._token
        result = await self.login()
        if not result.get("success") or not self._token:
            raise RuntimeError(
                f"Guacamole authentication failed: {result.get('error') or result.get('data')}"
            )
        return self._token

    async def _request(
        self,
        method: str,
        endpoint: str,
        json_data: dict | list | None = None,
        params: dict | None = None,
    ) -> dict[str, Any]:
        """Execute an authenticated Guacamole API request.

        Ensures a token is available (logging in lazily), then injects it as
        ``?token=`` alongside any caller-supplied query params. Mirrors the
        ``_request`` contract in ``gitea.py``.

        Args:
            method: HTTP method (GET, POST, PATCH, DELETE).
            endpoint: Path under ``base_url`` (e.g. ``/guacamole/api/...``).
            json_data: JSON body (dict or list - permission patches are
                arrays).
            params: Extra query parameters beyond the auth token.

        Returns:
            Uniform result dict with ``success``, ``status_code``, and either
            ``data`` or ``error``.
        """
        try:
            token = await self._ensure_token()
        except RuntimeError as e:
            return {"success": False, "error": str(e)}

        request_params = {"token": token}
        if params:
            request_params.update(params)

        async with self._new_client() as client:
            try:
                response = await client.request(
                    method=method,
                    url=endpoint,
                    json=json_data,
                    params=request_params,
                )

                result = {
                    "success": response.status_code in (200, 201, 204),
                    "status_code": response.status_code,
                }

                if response.text:
                    try:
                        result["data"] = response.json()
                    except ValueError:
                        result["data"] = response.text

                if not result["success"]:
                    logger.warning(
                        "guacamole_api_error",
                        method=method,
                        endpoint=endpoint,
                        status=response.status_code,
                        response=result.get("data"),
                    )

                return result

            except httpx.RequestError as e:
                logger.error(
                    "guacamole_request_error",
                    method=method,
                    endpoint=endpoint,
                    error=str(e),
                    exc_info=True,
                )
                return {
                    "success": False,
                    "error": str(e),
                }

    # =========================================================================
    # Connection Operations
    # =========================================================================

    async def list_connections(self) -> dict[str, Any]:
        """List all Guacamole connections.

        Returns:
            Uniform result dict. On success also includes a normalized
            ``connections`` list of ``{identifier, name, protocol}`` and a
            ``count``.
        """
        result = await self._request(
            "GET",
            f"/guacamole/api/session/data/{self._datasource}/connections",
        )

        if result["success"] and "data" in result:
            items = self._as_list(result["data"])
            result["connections"] = [
                {
                    "identifier": c.get("identifier"),
                    "name": c.get("name"),
                    "protocol": c.get("protocol"),
                }
                for c in items
                if isinstance(c, dict)
            ]
            result["count"] = len(result["connections"])

        return result

    async def create_connection(
        self,
        name: str,
        protocol: str,
        hostname: str,
        port: int | str,
        username: str | None = None,
        password: str | None = None,
        **extra_params: Any,
    ) -> dict[str, Any]:
        """Create a Guacamole connection (RDP/SSH/VNC/etc.).

        Args:
            name: Human-readable connection name (must be unique). This name
                is also used as the permission key when granting READ access.
            protocol: Guacamole protocol (``rdp``, ``ssh``, ``vnc``, ...).
            hostname: Target host.
            port: Target port. Coerced to string (Guacamole requires string
                parameter values).
            username: Optional protocol-level username (embedded in the
                connection so end users don't need to enter it).
            password: Optional protocol-level password.
            **extra_params: Additional protocol parameters merged into
                ``parameters``. Use ``**{"ignore-cert": "true"}`` for
                hyphenated keys.

        Returns:
            Uniform result dict. On success also includes ``connection_id``
            (the new connection's identifier) and ``name``.
        """
        parameters: dict[str, Any] = {
            "hostname": hostname,
            "port": str(port),
        }
        if username is not None:
            parameters["username"] = username
        if password is not None:
            parameters["password"] = password
        parameters.update(extra_params)

        body = {
            "name": name,
            "parentIdentifier": "ROOT",
            "protocol": protocol,
            "parameters": parameters,
            "attributes": {},
        }

        result = await self._request(
            "POST",
            f"/guacamole/api/session/data/{self._datasource}/connections",
            json_data=body,
        )

        if result["success"] and isinstance(result.get("data"), dict):
            result["connection_id"] = result["data"].get("identifier")
            result["name"] = result["data"].get("name")
            logger.info(
                "guacamole_connection_created",
                name=name,
                protocol=protocol,
                connection_id=result.get("connection_id"),
            )

        return result

    async def delete_connection(self, connection_id: str) -> dict[str, Any]:
        """Delete a Guacamole connection by identifier.

        Args:
            connection_id: The connection identifier (as returned by
                ``create_connection`` or found in ``list_connections``).

        Returns:
            Uniform result dict.
        """
        result = await self._request(
            "DELETE",
            f"/guacamole/api/session/data/{self._datasource}/connections/{connection_id}",
        )

        if result["success"]:
            logger.info("guacamole_connection_deleted", connection_id=connection_id)

        return result

    # =========================================================================
    # User / Permission Operations
    # =========================================================================

    async def get_user_id(self, username: str) -> str | None:
        """Resolve a Guacamole username to its user identifier.

        Args:
            username: Guacamole username to look up.

        Returns:
            The user's identifier (used in user-scoped URL paths), or ``None``
            if not found or the request failed.
        """
        result = await self._request(
            "GET",
            f"/guacamole/api/session/data/{self._datasource}/users",
        )

        if not result.get("success"):
            return None

        for user in self._as_list(result.get("data")):
            if not isinstance(user, dict):
                continue
            if user.get("username") == username or user.get("identifier") == username:
                identifier = user.get("identifier")
                if identifier:
                    return str(identifier)
        return None

    async def grant_read_permission(
        self,
        username: str,
        connection_name: str,
    ) -> dict[str, Any]:
        """Grant READ permission on a connection to a Guacamole user.

        Applies a JSON Patch (``op=add``) to the user's
        ``connectionPermissions`` for the given connection name.

        Args:
            username: Guacamole user to grant access to.
            connection_name: Name of the connection (the permission key).

        Returns:
            Uniform result dict. Fails with a descriptive ``error`` if the
            user cannot be found.
        """
        return await self._patch_connection_permission(
            username, connection_name, op="add", value="READ"
        )

    async def revoke_read_permission(
        self,
        username: str,
        connection_name: str,
    ) -> dict[str, Any]:
        """Revoke READ permission on a connection from a Guacamole user.

        Applies a JSON Patch (``op=remove``) to the user's
        ``connectionPermissions`` for the given connection name.

        Args:
            username: Guacamole user to revoke access from.
            connection_name: Name of the connection (the permission key).

        Returns:
            Uniform result dict. Fails with a descriptive ``error`` if the
            user cannot be found.
        """
        return await self._patch_connection_permission(
            username, connection_name, op="remove", value=None
        )

    async def _patch_connection_permission(
        self,
        username: str,
        connection_name: str,
        op: str,
        value: str | None,
    ) -> dict[str, Any]:
        """Shared helper for granting/removing a connection READ permission.

        Builds the single-element JSON Patch array and PATCHes the user
        resource. Creates the user first if they don't exist (OIDC users
        are auto-created on login but may not exist yet at VM creation time).
        """
        user_id = await self.get_user_id(username)
        if not user_id:
            create_result = await self._request(
                "POST",
                f"/guacamole/api/session/data/{self._datasource}/users",
                json_data={"username": username, "attributes": {}},
            )
            if not create_result.get("success"):
                return {
                    "success": False,
                    "error": f"Failed to create Guacamole user '{username}': {create_result.get('error')}",
                }
            user_id = create_result.get("data", {}).get("identifier")
            if not user_id:
                return {
                    "success": False,
                    "error": f"Guacamole user creation returned no identifier for '{username}'",
                }
            logger.info("guacamole_user_created", username=username, user_id=user_id)

        patch: list[dict[str, Any]] = [
            {"op": op, "path": f"/connectionPermissions/{connection_name}"}
        ]
        if value is not None:
            patch[0]["value"] = value

        result = await self._request(
            "PATCH",
            f"/guacamole/api/session/data/{self._datasource}/users/{user_id}",
            json_data=patch,
        )

        if result.get("success"):
            logger.info(
                "guacamole_permission_updated",
                op=op,
                username=username,
                connection=connection_name,
            )

        return result


def get_guacamole_client() -> GuacamoleClient:
    """Create a new GuacamoleClient instance.

    Stateless factory - returns a fresh client each time so it's safe across
    threads and event loops without shared mutable state. Mirrors
    ``get_gitea_client()``.
    """
    return GuacamoleClient()

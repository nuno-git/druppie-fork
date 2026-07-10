"""Test infrastructure for execution-layer unit tests.

The orchestrator and tool_executor transitively import `fastmcp`, whose 2.x
releases are incompatible with the bleeding-edge pydantic installed in some
local environments (and whose 3.x line requires source changes). Orchestrator
unit tests mock every real collaborator, so they never exercise fastmcp at
runtime. To let the orchestrator import cleanly for those tests we install a
minimal fastmcp stub when the real package cannot be imported.

The stub is only installed when `from fastmcp import Client` fails; in CI /
Docker (where fastmcp installs cleanly) the real package is used instead.
"""

import sys
import types


def _install_fastmcp_stub() -> None:
    try:
        from fastmcp import Client as _Client  # noqa: F401
        from fastmcp.client.transports import StreamableHttpTransport as _SHT  # noqa: F401

        return  # real fastmcp imports fine — nothing to do
    except Exception:
        pass

    fastmcp = types.ModuleType("fastmcp")

    class Client:  # placeholder; never called in unit tests (mocked)
        pass

    class FastMCP:
        pass

    fastmcp.Client = Client
    fastmcp.FastMCP = FastMCP
    sys.modules["fastmcp"] = fastmcp

    server = types.ModuleType("fastmcp.server")
    server_server = types.ModuleType("fastmcp.server.server")
    server_server.FastMCP = FastMCP
    sys.modules["fastmcp.server"] = server
    sys.modules["fastmcp.server.server"] = server_server

    client = types.ModuleType("fastmcp.client")
    transports = types.ModuleType("fastmcp.client.transports")

    class StreamableHttpTransport:
        pass

    transports.StreamableHttpTransport = StreamableHttpTransport
    sys.modules["fastmcp.client"] = client
    sys.modules["fastmcp.client.transports"] = transports


_install_fastmcp_stub()

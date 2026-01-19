"""Base class for MCP servers.

MCP servers implement the JSON-RPC 2.0 protocol over stdio.
"""

import json
import sys
from abc import ABC, abstractmethod
from typing import Any


class MCPServerBase(ABC):
    """Base class for MCP servers using JSON-RPC 2.0 over stdio."""

    def __init__(self):
        self.tools: dict[str, callable] = {}
        self._register_tools()

    @abstractmethod
    def _register_tools(self) -> None:
        """Register available tools. Override in subclass."""
        pass

    def run(self) -> None:
        """Run the server, reading from stdin and writing to stdout."""
        while True:
            try:
                line = sys.stdin.readline()
                if not line:
                    break

                request = json.loads(line)
                response = self._handle_request(request)
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()

            except json.JSONDecodeError as e:
                self._write_error(None, -32700, f"Parse error: {e}")
            except Exception as e:
                self._write_error(None, -32603, f"Internal error: {e}")

    def _handle_request(self, request: dict) -> dict:
        """Handle a JSON-RPC request."""
        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params", {})

        if method == "tools/call":
            return self._handle_tool_call(request_id, params)
        elif method == "tools/list":
            return self._handle_list_tools(request_id)
        else:
            return self._error_response(request_id, -32601, f"Method not found: {method}")

    def _handle_tool_call(self, request_id: Any, params: dict) -> dict:
        """Handle a tools/call request."""
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        if tool_name not in self.tools:
            return self._error_response(request_id, -32602, f"Tool not found: {tool_name}")

        try:
            result = self.tools[tool_name](**arguments)
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result,
            }
        except Exception as e:
            return self._error_response(request_id, -32000, str(e))

    def _handle_list_tools(self, request_id: Any) -> dict:
        """Handle a tools/list request."""
        tools = [
            {"name": name, "description": func.__doc__ or ""}
            for name, func in self.tools.items()
        ]
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"tools": tools},
        }

    def _error_response(self, request_id: Any, code: int, message: str) -> dict:
        """Create an error response."""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }

    def _write_error(self, request_id: Any, code: int, message: str) -> None:
        """Write an error response to stdout."""
        response = self._error_response(request_id, code, message)
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()

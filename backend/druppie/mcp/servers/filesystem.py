"""Filesystem MCP Server.

Provides file system operations via MCP protocol.
"""

import os
import glob as glob_module
import shutil
from typing import Any

from .base import MCPServerBase


class FilesystemMCPServer(MCPServerBase):
    """MCP Server for filesystem operations."""

    def __init__(self):
        super().__init__("filesystem", "Filesystem")
        self._register_tools()

    def _register_tools(self) -> None:
        """Register all filesystem tools."""
        self.register_tool("discover_files", self.discover_files)
        self.register_tool("read_file", self.read_file)
        self.register_tool("write_file", self.write_file)
        self.register_tool("move_file", self.move_file)
        self.register_tool("delete_file", self.delete_file)

    def discover_files(
        self,
        path: str,
        patterns: list[str] | None = None,
        recursive: bool = True,
    ) -> dict[str, Any]:
        """Scan a directory for files matching patterns."""
        try:
            if not os.path.exists(path):
                return {
                    "success": False,
                    "error": f"Path does not exist: {path}",
                }

            if not os.path.isdir(path):
                return {
                    "success": False,
                    "error": f"Path is not a directory: {path}",
                }

            files = []
            patterns = patterns or ["*"]

            for pattern in patterns:
                if recursive:
                    search_pattern = os.path.join(path, "**", pattern)
                    matches = glob_module.glob(search_pattern, recursive=True)
                else:
                    search_pattern = os.path.join(path, pattern)
                    matches = glob_module.glob(search_pattern)

                for match in matches:
                    if os.path.isfile(match):
                        files.append({
                            "path": match,
                            "name": os.path.basename(match),
                            "size": os.path.getsize(match),
                        })

            return {
                "success": True,
                "files": files,
                "count": len(files),
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    def read_file(self, path: str) -> dict[str, Any]:
        """Read the contents of a file."""
        try:
            if not os.path.exists(path):
                return {
                    "success": False,
                    "error": f"File does not exist: {path}",
                }

            if not os.path.isfile(path):
                return {
                    "success": False,
                    "error": f"Path is not a file: {path}",
                }

            # Check if file is too large (limit to 10MB)
            size = os.path.getsize(path)
            if size > 10 * 1024 * 1024:
                return {
                    "success": False,
                    "error": f"File is too large ({size} bytes). Max size is 10MB.",
                }

            # Try to read as text, fall back to binary info
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                return {
                    "success": True,
                    "content": content,
                    "size": size,
                    "encoding": "utf-8",
                }
            except UnicodeDecodeError:
                return {
                    "success": True,
                    "binary": True,
                    "size": size,
                    "message": "File is binary. Cannot return content.",
                }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    def write_file(self, path: str, content: str) -> dict[str, Any]:
        """Write content to a file."""
        try:
            # Ensure parent directory exists
            parent_dir = os.path.dirname(path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

            return {
                "success": True,
                "path": path,
                "size": len(content),
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    def move_file(self, source: str, destination: str) -> dict[str, Any]:
        """Move a file to a new location."""
        try:
            if not os.path.exists(source):
                return {
                    "success": False,
                    "error": f"Source does not exist: {source}",
                }

            # Ensure destination parent directory exists
            dest_parent = os.path.dirname(destination)
            if dest_parent:
                os.makedirs(dest_parent, exist_ok=True)

            shutil.move(source, destination)

            return {
                "success": True,
                "source": source,
                "destination": destination,
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    def delete_file(self, path: str) -> dict[str, Any]:
        """Delete a file."""
        try:
            if not os.path.exists(path):
                return {
                    "success": False,
                    "error": f"File does not exist: {path}",
                }

            if os.path.isdir(path):
                return {
                    "success": False,
                    "error": f"Path is a directory, not a file: {path}",
                }

            os.remove(path)

            return {
                "success": True,
                "deleted": path,
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }


def main():
    """Entry point for the Filesystem MCP server."""
    server = FilesystemMCPServer()
    server.run()


if __name__ == "__main__":
    main()

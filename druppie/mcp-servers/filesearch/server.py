"""File Search MCP Server.

Local file search with configurable search path (default: /dataset).
Uses FastMCP framework for HTTP transport.
"""

import logging
import os
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("filesearch-mcp")

# Initialize FastMCP server
mcp = FastMCP("File Search MCP Server")

# Configuration
SEARCH_ROOT = Path(os.getenv("SEARCH_ROOT", "/dataset"))

# =============================================================================
# MCP TOOLS
# =============================================================================


@mcp.tool()
async def search_files(
    query: str,
    path: str = ".",
    file_pattern: str = "*",
    max_results: int = 100,
    case_sensitive: bool = False,
) -> dict:
    """Search for files containing text content matching query.

    Args:
        query: Text to search for in file contents
        path: Search path relative to search root (default: ".")
        file_pattern: File pattern to match (default: "*", e.g., "*.py", "*.md")
        max_results: Maximum number of results to return (default: 100)
        case_sensitive: Whether search is case sensitive (default: False)

    Returns:
        Dict with success, results list, and metadata
    """
    try:
        search_path = (SEARCH_ROOT / path).resolve()

        # Security: ensure path is under search root
        try:
            search_path.relative_to(SEARCH_ROOT.resolve())
        except ValueError:
            return {"success": False, "error": f"Path traversal not allowed: {path}"}

        if not search_path.exists():
            return {"success": False, "error": f"Search path does not exist: {path}"}

        if not search_path.is_dir():
            return {"success": False, "error": f"Path is not a directory: {path}"}

        logger.info(
            "Searching in %s: query='%s' pattern='%s' case_sensitive=%s",
            search_path,
            query,
            file_pattern,
            case_sensitive,
        )

        results = []
        result_count = 0

        # Search in files
        for file_path in search_path.rglob(file_pattern):
            if result_count >= max_results:
                break

            # Skip directories
            if not file_path.is_file():
                continue

            # Skip common binary files
            if file_path.suffix in {".pyc", ".so", ".dll", ".exe", ".bin"}:
                continue

            # Skip large files (>10MB)
            if file_path.stat().st_size > 10 * 1024 * 1024:
                continue

            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")

                # Search for query in content
                search_query = query if case_sensitive else query.lower()
                search_content = content if case_sensitive else content.lower()

                if search_query in search_content:
                    # Find line numbers with matches
                    lines = content.split("\n")
                    matches = []

                    for i, line in enumerate(lines, 1):
                        line_search = line if case_sensitive else line.lower()
                        if search_query in line_search:
                            matches.append({
                                "line": i,
                                "text": line.strip(),
                            })
                            # Limit matches per file
                            if len(matches) >= 10:
                                break

                    if matches:
                        results.append({
                            "path": str(file_path.relative_to(SEARCH_ROOT)),
                            "full_path": str(file_path),
                            "matches": len(matches),
                            "file_size": file_path.stat().st_size,
                            "sample_matches": matches[:5],  # First 5 matches
                        })
                        result_count += 1

            except (UnicodeDecodeError, PermissionError, OSError):
                # Skip files that can't be read
                continue

        logger.info(
            "Search complete: %d results found for query='%s'",
            result_count,
            query,
        )

        return {
            "success": True,
            "query": query,
            "search_path": path,
            "results": results,
            "result_count": result_count,
            "truncated": result_count >= max_results,
        }

    except ValueError as e:
        logger.warning("Path resolution error: %s - %s", path, str(e))
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Search error: %s", str(e))
        return {"success": False, "error": str(e)}


@mcp.tool()
async def list_directory(
    path: str = ".",
    recursive: bool = False,
    show_hidden: bool = False,
) -> dict:
    """List files and directories in search path.

    Args:
        path: Path relative to search root (default: ".")
        recursive: Whether to list recursively (default: False)
        show_hidden: Whether to show hidden files starting with . (default: False)

    Returns:
        Dict with files, directories, and metadata
    """
    try:
        list_path = (SEARCH_ROOT / path).resolve()

        # Security: ensure path is under search root
        try:
            list_path.relative_to(SEARCH_ROOT.resolve())
        except ValueError:
            return {"success": False, "error": f"Path traversal not allowed: {path}"}

        if not list_path.exists():
            return {"success": False, "error": f"Path does not exist: {path}"}

        if not list_path.is_dir():
            return {"success": False, "error": f"Not a directory: {path}"}

        logger.info("Listing directory: %s (recursive=%s)", list_path, recursive)

        files = []
        directories = []

        if recursive:
            for item in list_path.rglob("*"):
                if not show_hidden and item.name.startswith("."):
                    continue
                if item.is_file():
                    files.append({
                        "name": item.name,
                        "path": str(item.relative_to(SEARCH_ROOT)),
                        "type": "file",
                        "size": item.stat().st_size,
                    })
                elif item.is_dir():
                    directories.append({
                        "name": item.name,
                        "path": str(item.relative_to(SEARCH_ROOT)),
                        "type": "directory",
                    })
        else:
            for item in list_path.iterdir():
                if not show_hidden and item.name.startswith("."):
                    continue
                if item.is_file():
                    files.append({
                        "name": item.name,
                        "path": str(item.relative_to(SEARCH_ROOT)),
                        "type": "file",
                        "size": item.stat().st_size,
                    })
                elif item.is_dir():
                    directories.append({
                        "name": item.name,
                        "path": str(item.relative_to(SEARCH_ROOT)),
                        "type": "directory",
                    })

        return {
            "success": True,
            "path": path,
            "files": files,
            "directories": directories,
            "file_count": len(files),
            "directory_count": len(directories),
        }

    except ValueError as e:
        logger.warning("Path resolution error: %s - %s", path, str(e))
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("List directory error: %s", str(e))
        return {"success": False, "error": str(e)}


@mcp.tool()
async def read_file(path: str) -> dict:
    """Read file content from search path.

    Args:
        path: File path relative to search root

    Returns:
        Dict with success, content, and file metadata
    """
    try:
        file_path = (SEARCH_ROOT / path).resolve()

        # Security: ensure path is under search root
        try:
            file_path.relative_to(SEARCH_ROOT.resolve())
        except ValueError:
            return {"success": False, "error": f"Path traversal not allowed: {path}"}

        logger.info("Reading file: %s", file_path)

        if not file_path.exists():
            return {"success": False, "error": f"File not found: {path}"}

        if not file_path.is_file():
            return {"success": False, "error": f"Not a file: {path}"}

        # Check size limit (10MB)
        size = file_path.stat().st_size
        if size > 10 * 1024 * 1024:
            return {"success": False, "error": f"File too large: {size} bytes"}

        try:
            content = file_path.read_text(encoding="utf-8")
            return {
                "success": True,
                "path": str(file_path.relative_to(SEARCH_ROOT)),
                "size": size,
                "line_count": len(content.split("\n")),
                "content": content,
            }
        except UnicodeDecodeError:
            return {
                "success": False,
                "error": "File is binary",
                "path": str(file_path.relative_to(SEARCH_ROOT)),
                "size": size,
            }

    except ValueError as e:
        logger.warning("Path resolution error: %s - %s", path, str(e))
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Read file error: %s", str(e))
        return {"success": False, "error": str(e)}


@mcp.tool()
async def get_search_stats(path: str = ".") -> dict:
    """Get statistics about files in search path.

    Args:
        path: Path relative to search root (default: ".")

    Returns:
        Dict with file counts, sizes, and file type breakdown
    """
    try:
        stats_path = (SEARCH_ROOT / path).resolve()

        # Security: ensure path is under search root
        try:
            stats_path.relative_to(SEARCH_ROOT.resolve())
        except ValueError:
            return {"success": False, "error": f"Path traversal not allowed: {path}"}

        if not stats_path.exists():
            return {"success": False, "error": f"Path does not exist: {path}"}

        if not stats_path.is_dir():
            return {"success": False, "error": f"Not a directory: {path}"}

        logger.info("Getting stats for: %s", stats_path)

        stats = {
            "total_files": 0,
            "total_directories": 0,
            "total_size": 0,
            "file_types": {},
            "largest_files": [],
        }

        for item in stats_path.rglob("*"):
            if item.is_file():
                stats["total_files"] += 1
                size = item.stat().st_size
                stats["total_size"] += size

                # Track file types
                ext = item.suffix.lower() or "no_extension"
                stats["file_types"][ext] = stats["file_types"].get(ext, 0) + 1

                # Track largest files (top 10)
                stats["largest_files"].append({
                    "path": str(item.relative_to(SEARCH_ROOT)),
                    "size": size,
                })
                stats["largest_files"].sort(key=lambda x: x["size"], reverse=True)
                stats["largest_files"] = stats["largest_files"][:10]

            elif item.is_dir():
                stats["total_directories"] += 1

        return {
            "success": True,
            "path": path,
            "stats": stats,
        }

    except Exception as e:
        logger.error("Get stats error: %s", str(e))
        return {"success": False, "error": str(e)}


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    # Get MCP app with HTTP transport
    app = mcp.http_app()

    # Add health endpoint
    async def health(request):
        """Health check endpoint."""
        return JSONResponse({"status": "healthy", "service": "filesearch-mcp"})

    app.routes.insert(0, Route("/health", health, methods=["GET"]))

    port = int(os.getenv("MCP_PORT", "9004"))

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )

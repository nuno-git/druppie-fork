"""File Search MCP Server - Business Logic Module.

Contains all business logic for file search operations.
"""

import logging
from pathlib import Path

logger = logging.getLogger("filesearch-mcp")


class FileSearchModule:
    """Business logic module for file search operations."""

    def __init__(self, search_root):
        self.search_root = Path(search_root)

    def _validate_path(self, path: str) -> tuple[Path | None, str | None]:
        """Validate and resolve path relative to search root."""
        try:
            resolved_path = (self.search_root / path).resolve()
            resolved_path.relative_to(self.search_root.resolve())
            return resolved_path, None
        except ValueError:
            return None, f"Path traversal not allowed: {path}"
        except Exception as e:
            return None, str(e)

    def search_files(
        self,
        query: str,
        path: str = ".",
        file_pattern: str = "*",
        max_results: int = 100,
        case_sensitive: bool = False,
    ) -> dict:
        """Search for files containing text content matching query."""
        search_path, error = self._validate_path(path)
        if error:
            return {"success": False, "error": error}

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

        for file_path in search_path.rglob(file_pattern):
            if result_count >= max_results:
                break

            if not file_path.is_file():
                continue

            if file_path.suffix in {".pyc", ".so", ".dll", ".exe", ".bin"}:
                continue

            if file_path.stat().st_size > 10 * 1024 * 1024:
                continue

            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")

                search_query = query if case_sensitive else query.lower()
                search_content = content if case_sensitive else content.lower()

                if search_query in search_content:
                    lines = content.split("\n")
                    matches = []

                    for i, line in enumerate(lines, 1):
                        line_search = line if case_sensitive else line.lower()
                        if search_query in line_search:
                            matches.append({
                                "line": i,
                                "text": line.strip(),
                            })
                            if len(matches) >= 10:
                                break

                    if matches:
                        results.append({
                            "path": str(file_path.relative_to(self.search_root)),
                            "full_path": str(file_path),
                            "matches": len(matches),
                            "file_size": file_path.stat().st_size,
                            "sample_matches": matches[:5],
                        })
                        result_count += 1

            except (UnicodeDecodeError, PermissionError, OSError):
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

    def list_directory(
        self,
        path: str = ".",
        recursive: bool = False,
        show_hidden: bool = False,
    ) -> dict:
        """List files and directories in search path."""
        list_path, error = self._validate_path(path)
        if error:
            return {"success": False, "error": error}

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
                        "path": str(item.relative_to(self.search_root)),
                        "type": "file",
                        "size": item.stat().st_size,
                    })
                elif item.is_dir():
                    directories.append({
                        "name": item.name,
                        "path": str(item.relative_to(self.search_root)),
                        "type": "directory",
                    })
        else:
            for item in list_path.iterdir():
                if not show_hidden and item.name.startswith("."):
                    continue
                if item.is_file():
                    files.append({
                        "name": item.name,
                        "path": str(item.relative_to(self.search_root)),
                        "type": "file",
                        "size": item.stat().st_size,
                    })
                elif item.is_dir():
                    directories.append({
                        "name": item.name,
                        "path": str(item.relative_to(self.search_root)),
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

    def read_file(self, path: str) -> dict:
        """Read file content from search path."""
        file_path, error = self._validate_path(path)
        if error:
            return {"success": False, "error": error}

        logger.info("Reading file: %s", file_path)

        if not file_path.exists():
            return {"success": False, "error": f"File not found: {path}"}

        if not file_path.is_file():
            return {"success": False, "error": f"Not a file: {path}"}

        size = file_path.stat().st_size
        if size > 10 * 1024 * 1024:
            return {"success": False, "error": f"File too large: {size} bytes"}

        try:
            content = file_path.read_text(encoding="utf-8")
            return {
                "success": True,
                "path": str(file_path.relative_to(self.search_root)),
                "size": size,
                "line_count": len(content.split("\n")),
                "content": content,
            }
        except UnicodeDecodeError:
            return {
                "success": False,
                "error": "File is binary",
                "path": str(file_path.relative_to(self.search_root)),
                "size": size,
            }

    def get_search_stats(self, path: str = ".") -> dict:
        """Get statistics about files in search path."""
        stats_path, error = self._validate_path(path)
        if error:
            return {"success": False, "error": error}

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

                ext = item.suffix.lower() or "no_extension"
                stats["file_types"][ext] = stats["file_types"].get(ext, 0) + 1

                stats["largest_files"].append({
                    "path": str(item.relative_to(self.search_root)),
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

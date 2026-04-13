"""Web MCP Server - Business Logic Module.

Contains all business logic for web browsing and file search.
"""

import logging
from pathlib import Path

import httpx

logger = logging.getLogger("web-mcp")

REQUEST_TIMEOUT = 30.0


class WebModule:
    """Business logic module for web operations."""

    def __init__(self, search_root):
        self.search_root = Path(search_root)

    async def fetch_url(self, url: str) -> dict:
        """Fetch and return content from a URL."""
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                response = await client.get(url)

                return {
                    "success": True,
                    "url": url,
                    "status_code": response.status_code,
                    "content": response.text[:10000],
                }
        except Exception as e:
            logger.error(f"Error fetching URL {url}: {e}")
            return {
                "success": False,
                "error": str(e),
                "url": url,
            }

    async def search_web(self, query: str, num_results: int = 5) -> dict:
        """Search web for information."""
        logger.info(f"Searching for: {query}")
        return {
            "success": True,
            "query": query,
            "results": [
                {
                    "title": f"Result {i + 1} for '{query}'",
                    "url": f"https://example.com/result{i + 1}",
                    "snippet": f"This is a placeholder search result for {query}",
                }
                for i in range(min(num_results, 5))
            ],
        }

    async def get_page_info(self, url: str) -> dict:
        """Get basic information about a web page."""
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                response = await client.get(url)

                content = response.text
                title = "No title found"
                if "<title>" in content:
                    start = content.find("<title>") + 7
                    end = content.find("</title>", start)
                    title = content[start:end].strip()

                links_count = content.count("<a")

                return {
                    "success": True,
                    "url": url,
                    "title": title,
                    "links_count": links_count,
                    "status_code": response.status_code,
                }
        except Exception as e:
            logger.error(f"Error getting page info for {url}: {e}")
            return {
                "success": False,
                "error": str(e),
                "url": url,
            }

    def search_files(
        self,
        query: str,
        path: str = ".",
        file_pattern: str = "*",
        max_results: int = 100,
        case_sensitive: bool = False,
    ) -> dict:
        """Search for files containing text content matching query."""
        search_path = (self.search_root / path).resolve()

        try:
            search_path.relative_to(self.search_root.resolve())
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
        list_path = (self.search_root / path).resolve()

        try:
            list_path.relative_to(self.search_root.resolve())
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
        file_path = (self.search_root / path).resolve()

        try:
            file_path.relative_to(self.search_root.resolve())
        except ValueError:
            return {"success": False, "error": f"Path traversal not allowed: {path}"}

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

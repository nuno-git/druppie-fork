"""File-path access validation for agent sandbox constraints.

Enforces allowed_paths / forbidden_paths from agent YAML definitions.
Constraints apply to WRITE operations only (write_file, edit_file, delete_file,
batch_write_files). Read operations (read_file, grep, find, ls) are unrestricted
so agents can read cross-boundary code for context.
"""

import fnmatch
import posixpath


FILE_WRITE_TOOLS = frozenset({
    "write_file", "edit_file", "delete_file", "batch_write_files",
})


def extract_file_paths(tool_name: str, args: dict) -> list[str]:
    """Extract file paths from tool arguments."""
    paths = []
    if tool_name == "batch_write_files":
        for f in args.get("files", []):
            if isinstance(f, dict) and f.get("path"):
                paths.append(f["path"])
    elif "path" in args:
        paths.append(args["path"])
    elif "file_path" in args:
        paths.append(args["file_path"])
    return paths


def normalize_path(path: str) -> str:
    """Normalize a file path for pattern matching (resolve ../, strip leading /)."""
    return posixpath.normpath(path.replace("\\", "/")).lstrip("/")


def path_matches_pattern(normalized_path: str, pattern: str) -> bool:
    """Check if a normalized path matches an allowed/forbidden pattern.

    Patterns:
    - "src/components/" — directory prefix, matches files under that dir
    - "*.tsx" — extension glob, matches basename
    - "src/App.*" — multi-segment glob, matched against full path
    - "package.json" — exact filename, matched against basename
    """
    if pattern.endswith("/"):
        return (
            normalized_path.startswith(pattern)
            or normalized_path + "/" == pattern
        )
    if "/" in pattern:
        return fnmatch.fnmatch(normalized_path, pattern)
    basename = normalized_path.rsplit("/", 1)[-1]
    return fnmatch.fnmatch(basename, pattern)


def validate_file_path_access(
    tool_name: str,
    arguments: dict,
    agent_id: str,
    allowed_paths: list[str] | None,
    forbidden_paths: list[str] | None,
) -> str | None:
    """Validate that file paths in tool arguments comply with agent path constraints.

    Forbidden paths are checked first — a match is immediately rejected.
    Allowed paths are checked second — the path must match at least one.
    Only enforced on write tools (write_file, edit_file, delete_file, batch_write_files).

    Returns an error message if access is denied, None if allowed.
    """
    if not allowed_paths and not forbidden_paths:
        return None

    if tool_name not in FILE_WRITE_TOOLS:
        return None

    paths = extract_file_paths(tool_name, arguments or {})
    if not paths:
        return None

    for path in paths:
        normalized = normalize_path(path)

        if forbidden_paths:
            for pattern in forbidden_paths:
                if path_matches_pattern(normalized, pattern):
                    return (
                        f"Agent '{agent_id}' is forbidden from writing to "
                        f"path '{path}' (matches forbidden pattern '{pattern}'). "
                        f"Delegate to the appropriate specialist agent."
                    )

        if allowed_paths:
            if not any(
                path_matches_pattern(normalized, pattern)
                for pattern in allowed_paths
            ):
                return (
                    f"Agent '{agent_id}' is not allowed to write to "
                    f"path '{path}'. Allowed patterns: {allowed_paths}. "
                    f"Delegate to the appropriate specialist agent."
                )

    return None

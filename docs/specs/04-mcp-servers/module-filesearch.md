# module-filesearch

**Port:** 9004. **Type:** core. **Dockerfile:** `druppie/mcp-servers/module-filesearch/Dockerfile`.

Read-only file search over `/dataset`. 4 tools.

## Dockerfile

Identical pattern to `module-web` — Python 3.11 slim, curl, `SEARCH_ROOT=/dataset`, port 9004.

## Tools

### `search_files`

Args: `query`, `path?`, `file_pattern?`, `max_results?`, `case_sensitive?`.

### `list_directory`

Args: `path?`, `recursive?`, `show_hidden?`.

### `read_file`

Args: `path`.

### `get_search_stats`

Args: `path?`.

Returns `{total_files, total_size_bytes, by_extension: {py: 42, md: 18, …}}` — used by the UI and for diagnostics.

## Notes

- Largely overlaps with `module-web`'s file tools. The separation exists because `module-web` also does HTTP fetching; `module-filesearch` is a narrower tool set for agents that shouldn't have HTTP access.
- Path validation via `_validate_path()` prevents escaping `SEARCH_ROOT` through `..` or absolute paths.

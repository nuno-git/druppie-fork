# module-web

**Port:** 9005. **Type:** both (agents + deployed apps via SDK). **Dockerfile:** `druppie/mcp-servers/module-web/Dockerfile`.

Local file search (over `/dataset`) plus HTTP fetch and web search. 6 tools.

## Dockerfile

- Base: `python:3.11-slim`.
- Installs `curl`.
- `SEARCH_ROOT=/dataset`, mounted from `druppie_new_dataset` volume.
- Expose 9005.
- Healthcheck: `curl -f http://localhost:9005/health`.

## `requirements.txt`

- `httpx`
- `fastmcp>=2.0.0,<3.0.0`
- `uvicorn`
- `pyyaml`

## Tools (6)

### `search_files`

Args: `query`, `path?`, `file_pattern?`, `max_results?`, `case_sensitive?`.

Searches `/dataset` (or subdir) for files containing the query string. Respects `file_pattern` glob.

### `list_directory`

Args: `path?`, `recursive?`, `show_hidden?`.

Identical semantics to `filesearch:list_directory` — same underlying `WebModule._validate_path()` prevents path traversal.

### `read_file`

Args: `path`.

Reads a file under `SEARCH_ROOT`. Path validated to be within the search root.

### `fetch_url`

Args: `url`.

Async HTTP GET via `httpx.AsyncClient` with 30 s timeout. Returns first 10 000 chars of the body (to prevent context bombs).

### `search_web`

Args: `query`, `num_results?`.

**Stub** in current code — returns placeholder results. The real implementation will plug into a search API (Brave / Bing / Tavily) but the integration isn't wired. Agents that call this still get a structured response they can gracefully handle.

### `get_page_info`

Args: `url`.

Fetches HEAD + small GET, returns `{url, status, content_type, length, title?}`.

## Used by

- **router** (`druppie/agents/definitions/router.yaml`) — lets the router look up files in the knowledge set when deciding intent.
- **architect** (indirectly via skills that recommend web lookups).

## `/dataset` volume

A read-only dataset directory on the host, mounted at `/dataset` into both `module-web` and `module-filesearch`. Intended for reference docs, exemplar projects, NORA principles, Water-authority architecture standards, etc. Content is curated per deployment — there is no seed script.

## Security

- `SEARCH_ROOT` is validated on every path — trying to `../../etc/passwd` is rejected.
- `fetch_url` currently accepts any URL. There is no SSRF allowlist. For production, front this behind an egress proxy.
- Body size capped at 10 KB return.

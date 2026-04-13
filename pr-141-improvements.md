# PR #141 — Improvements

## 1. Don't generate ARCHITECTURE_AUTO.md — the page already shows this live

The orchestrator now generates a markdown file with a table of agents and tools after every core update. But the architecture page already shows this exact same data live via the API — interactive, filterable, always up-to-date.

The generated file adds no value. It's just a static copy of what the API already serves. Remove the generation code from the orchestrator and remove the file from the docs tab.

If someone ever needs a static export, add a download button on the page.

## 2. Don't put documentation logic in the orchestrator

The orchestrator runs agents. It shouldn't know about architecture pages, markdown generation, or cache clearing. Right now there's a special case: "if the agent that just finished is update_core_builder, clear caches and write a markdown file." That doesn't belong there.

Move the cache clearing to the `/api/architecture/refresh` endpoint (which already exists). Call it from wherever makes sense — the frontend, a hook, or a simple check on the architecture page load.

## 3. Cache clearing is fragile

The code directly pokes into private internals of other modules:
```python
AgentDefinitionLoader._cache.clear()
mcp_config._config = None
```

If someone refactors those modules, this breaks without anyone noticing. Add a proper `clear_cache()` method to those modules instead. Or even simpler — the agent loader already watches file modification times, so it auto-refreshes when YAMLs change on disk. It might not even need manual cache clearing.

## 4. Workflow rules — keep as config, not Python code

The agent connections (router→planner→BA→architect→...) are hardcoded in Python. These come from how the planner decides routing, which is prompt-based — so we can't derive them automatically.

But they shouldn't be buried in Python code either. Move them to a `workflow.yaml` file so they're easy to find and edit when the flow changes. Same pattern as agent definitions — config in YAML, not code.

## 5. Don't parse YAML files 3 times per page load

Opening the architecture page calls 3 endpoints, and each one reads and parses all agent YAML files independently. That's ~14 files parsed 3 times.

Either cache the parsed results (with a file modification time check), or combine into a single endpoint that returns everything at once.

## 6. Mount docs as read-only

The `./docs` volume mount should be `:ro` (read-only). Right now the container can write to the host's docs folder, which is how `ARCHITECTURE_AUTO.md` gets generated. If we remove the generation (point 1), the mount only needs to serve docs — read-only is safer.

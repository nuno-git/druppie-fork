"""SearXNG MCP Server — Version Router."""

from module_router import create_module_app, run_module

app = create_module_app("searxng", default_port=9014)

if __name__ == "__main__":
    run_module("searxng", default_port=9014)

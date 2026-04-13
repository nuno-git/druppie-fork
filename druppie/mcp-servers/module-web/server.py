"""Web MCP Server — Version Router."""

from module_router import create_module_app, run_module

app = create_module_app("web", default_port=9005)

if __name__ == "__main__":
    run_module("web", default_port=9005)

"""Vision MCP Server — Version Router."""

from module_router import create_module_app, run_module

app = create_module_app("vision", default_port=9011)

if __name__ == "__main__":
    run_module("vision", default_port=9011)

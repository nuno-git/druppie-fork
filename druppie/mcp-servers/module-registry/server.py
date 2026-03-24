"""Registry MCP Server — Version Router."""

from module_router import create_module_app, run_module

app = create_module_app("registry", default_port=9007)

if __name__ == "__main__":
    run_module("registry", default_port=9007)

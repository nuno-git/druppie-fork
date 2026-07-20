"""Browser MCP Server — Version Router."""

from module_router import create_module_app, run_module

app = create_module_app("browser", default_port=9015)

if __name__ == "__main__":
    run_module("browser", default_port=9015)

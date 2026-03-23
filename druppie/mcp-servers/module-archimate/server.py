"""ArchiMate MCP Server — Version Router."""

from module_router import create_module_app, run_module

app = create_module_app("archimate", default_port=9006)

if __name__ == "__main__":
    run_module("archimate", default_port=9006)

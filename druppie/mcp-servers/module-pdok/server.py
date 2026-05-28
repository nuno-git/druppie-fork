"""PDOK MCP Server — Version Router."""

from module_router import create_module_app, run_module

app = create_module_app("pdok", default_port=9022)

if __name__ == "__main__":
    run_module("pdok", default_port=9022)

"""Objectstore MCP Server — Version Router."""

from module_router import create_module_app, run_module

app = create_module_app("objectstore", default_port=9204)

if __name__ == "__main__":
    run_module("objectstore", default_port=9204)

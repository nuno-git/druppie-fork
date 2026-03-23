"""Coding MCP Server — Version Router."""

from module_router import create_module_app, run_module

app = create_module_app("coding", default_port=9001)

if __name__ == "__main__":
    run_module("coding", default_port=9001)

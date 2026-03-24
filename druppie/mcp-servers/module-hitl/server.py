"""HITL MCP Server — Version Router."""

from module_router import create_module_app, run_module

app = create_module_app("hitl", default_port=9003)

if __name__ == "__main__":
    run_module("hitl", default_port=9003)

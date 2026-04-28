"""Foundry MCP Server — Version Router."""

from module_router import create_module_app, run_module

app = create_module_app("foundry", default_port=9012)

if __name__ == "__main__":
    run_module("foundry", default_port=9012)

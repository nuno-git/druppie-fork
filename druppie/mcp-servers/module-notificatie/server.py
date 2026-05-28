"""Notificatie MCP Server — Version Router."""

from module_router import create_module_app, run_module

app = create_module_app("notificatie", default_port=9021)

if __name__ == "__main__":
    run_module("notificatie", default_port=9021)

"""File Search MCP Server — Version Router."""

from module_router import create_module_app, run_module

app = create_module_app("filesearch", default_port=9004)

if __name__ == "__main__":
    run_module("filesearch", default_port=9004)

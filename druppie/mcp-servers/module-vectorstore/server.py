"""Vector Store MCP Server — Version Router."""

from module_router import create_module_app, run_module

app = create_module_app("vectorstore", default_port=9012)

if __name__ == "__main__":
    run_module("vectorstore", default_port=9012)

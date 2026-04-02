"""Docker MCP Server — Version Router."""

from module_router import create_module_app, run_module

app = create_module_app("docker", default_port=9002)

if __name__ == "__main__":
    run_module("docker", default_port=9002)

"""Object Storage MCP Server — Version Router."""

from module_router import create_module_app, run_module

app = create_module_app("objectstorage", default_port=9023)

if __name__ == "__main__":
    run_module("objectstorage", default_port=9023)

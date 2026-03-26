"""Azure Data Lake MCP Server — Version Router."""

from module_router import create_module_app, run_module

app = create_module_app("azure-datalake", default_port=9008)

if __name__ == "__main__":
    run_module("azure-datalake", default_port=9008)

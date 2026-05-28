"""PDOK Geocode MCP Server — Version Router."""

from module_router import create_module_app, run_module

app = create_module_app("pdok-geocode", default_port=9203)

if __name__ == "__main__":
    run_module("pdok-geocode", default_port=9203)

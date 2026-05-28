"""DSP-ZGW MCP Server — Version Router."""

from module_router import create_module_app, run_module

app = create_module_app("dsp-zgw", default_port=9020)

if __name__ == "__main__":
    run_module("dsp-zgw", default_port=9020)

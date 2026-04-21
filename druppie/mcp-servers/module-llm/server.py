"""LLM MCP Server — Version Router."""

from module_router import create_module_app, run_module

app = create_module_app("llm", default_port=9008)

if __name__ == "__main__":
    run_module("llm", default_port=9008)

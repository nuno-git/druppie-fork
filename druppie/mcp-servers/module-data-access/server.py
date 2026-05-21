"""Data Access MCP Server — Version Router."""

import os
import uvicorn
from module_router import create_module_app

app = create_module_app("dataaccess", default_port=9010)

if __name__ == "__main__":
    port = int(os.getenv("MCP_PORT", "9010"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
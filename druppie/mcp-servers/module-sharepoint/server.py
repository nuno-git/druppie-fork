"""SharePoint MCP Server — Version Router.

Read-only access to files in a configured SharePoint folder via Microsoft
Graph API. The SharePoint site and folder are fixed via the SHAREPOINT_SITE_ID
and SHAREPOINT_FOLDER_PATH env vars and are never taken from a tool argument,
so agents cannot read any other site or folder.
"""

import os
import uvicorn
from module_router import create_module_app

app = create_module_app("sharepoint", default_port=9014)

if __name__ == "__main__":
    port = int(os.getenv("MCP_PORT", "9014"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")

"""SharePoint MCP Server — Version Router.

Read-only access to SharePoint sites via Microsoft Graph API. Agents discover
sites with list_sites, then browse and read files using the returned site IDs.
Access is scoped by SHAREPOINT_ALLOWED_SITES (URL allowlist) and OBO auth.
"""

import os
import uvicorn
from module_router import create_module_app

app = create_module_app("sharepoint", default_port=9014)

if __name__ == "__main__":
    port = int(os.getenv("MCP_PORT", "9014"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")

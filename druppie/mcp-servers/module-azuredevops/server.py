"""Azure DevOps MCP Server — Version Router.

Read-only access to backlog / work items of a SINGLE, server-configured Azure
DevOps project. The project is fixed via the AZURE_DEVOPS_PROJECT env var and is
never taken from a tool argument, so agents cannot read any other project.
"""

import os
import uvicorn
from module_router import create_module_app

app = create_module_app("azuredevops", default_port=9012)

if __name__ == "__main__":
    port = int(os.getenv("MCP_PORT", "9012"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")

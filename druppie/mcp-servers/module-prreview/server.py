"""PR Review MCP Server — Version Router.

Reviews pull requests on a SINGLE, server-configured set of Gitea repositories.
The Gitea instance and the repo allowlist are fixed via PRREVIEW_* env vars and
are never taken from tool arguments, so agents cannot point the tools at any
other Gitea instance or repository.
"""

import os

import uvicorn
from module_router import create_module_app

app = create_module_app("prreview", default_port=9014)

if __name__ == "__main__":
    port = int(os.getenv("MCP_PORT", "9014"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")

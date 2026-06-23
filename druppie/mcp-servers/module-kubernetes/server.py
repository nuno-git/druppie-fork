"""Kubernetes MCP Server — Version Router.

Read-only access to Kubernetes cluster status. Uses in-cluster config when
running inside a pod, falls back to default kubeconfig for local development.
"""

from module_router import create_module_app, run_module

app = create_module_app("kubernetes", default_port=9013)

if __name__ == "__main__":
    run_module("kubernetes", default_port=9013)

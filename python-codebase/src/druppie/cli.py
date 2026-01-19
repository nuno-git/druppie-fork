"""Command-line interface for Druppie."""

import asyncio
import sys

import structlog
import uvicorn

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ]
)

logger = structlog.get_logger()


def main():
    """Main entry point for the CLI."""
    if len(sys.argv) < 2:
        print_help()
        return

    command = sys.argv[1]

    if command == "serve":
        serve()
    elif command == "run":
        if len(sys.argv) < 3:
            print("Usage: druppie run <workflow_id>")
            return
        run_workflow(sys.argv[2])
    elif command == "list":
        list_items()
    elif command == "help":
        print_help()
    else:
        print(f"Unknown command: {command}")
        print_help()


def print_help():
    """Print help message."""
    print(
        """
Druppie - Lightweight AI workflow orchestration

Commands:
    serve           Start the API server
    run <workflow>  Run a workflow manually
    list            List workflows and plans
    help            Show this help message

Examples:
    druppie serve
    druppie run vergunning_zoeker
    druppie list
"""
    )


def serve():
    """Start the API server."""
    logger.info("Starting Druppie server")
    uvicorn.run(
        "druppie.api.main:app",
        host="0.0.0.0",
        port=8080,
        reload=True,
    )


def run_workflow(workflow_id: str):
    """Run a workflow manually."""
    from druppie.store import FileStore
    from druppie.mcp import MCPRegistry

    async def _run():
        store = FileStore()
        workflow = await store.get_workflow(workflow_id)

        if not workflow:
            print(f"Workflow not found: {workflow_id}")
            return

        print(f"Running workflow: {workflow.name}")
        # TODO: Actually execute the workflow
        print("Workflow execution not yet implemented in CLI")

    asyncio.run(_run())


def list_items():
    """List workflows and plans."""
    from druppie.store import FileStore

    async def _list():
        store = FileStore()

        print("\n=== Workflows ===")
        workflows = await store.list_workflows()
        if workflows:
            for w in workflows:
                schedule = f" [{w.schedule}]" if w.schedule else ""
                print(f"  {w.id}: {w.name} ({w.status}){schedule}")
        else:
            print("  No workflows found")

        print("\n=== Plans ===")
        plans = await store.list_plans(limit=10)
        if plans:
            for p in plans:
                print(f"  {p.id}: {p.name} ({p.status.value})")
        else:
            print("  No plans found")

        print()

    asyncio.run(_list())


if __name__ == "__main__":
    main()

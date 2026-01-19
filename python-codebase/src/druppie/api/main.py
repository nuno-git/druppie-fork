"""FastAPI application for Druppie Governance Platform.

Simplified architecture with:
- Router: Classifies intent (create_project, update_project, general_chat)
- Planner: Selects workflows OR agents
- Orchestrator: Routes to WorkflowEngine or AgentRuntime
"""

import json
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import structlog
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from langchain_ollama import ChatOllama
from pydantic import BaseModel

# Load .env file from project root
load_dotenv(Path(__file__).parent.parent.parent.parent / ".env")

from druppie.agents import AgentRuntime
from druppie.core.models import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    Plan,
    PlanStatus,
    PlanType,
)
from druppie.llm import ChatZAI
from druppie.mcp import MCPClient, MCPRegistry
from druppie.orchestrator import Orchestrator
from druppie.planner import Planner
from druppie.registry import AgentRegistry
from druppie.router import Router
from druppie.store import FileStore
from druppie.workflows import WorkflowEngine, WorkflowRegistry

logger = structlog.get_logger()


# --- Configuration ---


class Config:
    """Application configuration."""

    # LLM Provider: "ollama" or "zai"
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "ollama")

    # Ollama Configuration
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
    OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")

    # Z.AI Configuration
    ZAI_API_KEY: str = os.getenv("ZAI_API_KEY", "")
    ZAI_MODEL: str = os.getenv("ZAI_MODEL", "GLM-4.7")
    ZAI_BASE_URL: str = os.getenv(
        "ZAI_BASE_URL", "https://api.z.ai/api/coding/paas/v4"
    )

    # Registry
    REGISTRY_PATH: str = os.getenv("REGISTRY_PATH", "registry")

    # Workspace for file operations
    WORKSPACE_PATH: str = os.getenv("WORKSPACE_PATH", "/tmp/druppie-workspace")


config = Config()


# --- Request/Response Models ---


class CreatePlanRequest(BaseModel):
    """Request to create a new plan."""

    name: str
    description: str | None = None
    input_data: dict[str, Any] = {}


# --- Application State ---


class AppState:
    """Application state container."""

    def __init__(self):
        self.store: FileStore | None = None
        self.mcp_registry: MCPRegistry | None = None
        self.mcp_client: MCPClient | None = None
        self.agent_registry: AgentRegistry | None = None
        self.workflow_registry: WorkflowRegistry | None = None
        self.llm = None
        self.router: Router | None = None
        self.planner: Planner | None = None
        self.agent_runtime: AgentRuntime | None = None
        self.workflow_engine: WorkflowEngine | None = None
        self.orchestrator: Orchestrator | None = None


app_state = AppState()


# --- Dependencies ---


def get_store() -> FileStore:
    if not app_state.store:
        raise HTTPException(500, "Store not initialized")
    return app_state.store


def get_mcp_registry() -> MCPRegistry:
    if not app_state.mcp_registry:
        raise HTTPException(500, "MCP Registry not initialized")
    return app_state.mcp_registry


def get_mcp_client() -> MCPClient:
    if not app_state.mcp_client:
        raise HTTPException(500, "MCP Client not initialized")
    return app_state.mcp_client


def get_agent_registry() -> AgentRegistry:
    if not app_state.agent_registry:
        raise HTTPException(500, "Agent Registry not initialized")
    return app_state.agent_registry


def get_workflow_registry() -> WorkflowRegistry:
    if not app_state.workflow_registry:
        raise HTTPException(500, "Workflow Registry not initialized")
    return app_state.workflow_registry


def get_router() -> Router | None:
    return app_state.router


def get_planner() -> Planner | None:
    return app_state.planner


def get_orchestrator() -> Orchestrator | None:
    return app_state.orchestrator


# --- Lifespan ---


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("Starting Druppie Governance Platform")

    # Create workspace directory
    Path(config.WORKSPACE_PATH).mkdir(parents=True, exist_ok=True)

    # Initialize store
    app_state.store = FileStore()

    # Initialize LLM based on provider configuration
    try:
        if config.LLM_PROVIDER.lower() == "zai":
            if not config.ZAI_API_KEY:
                logger.warning("Z.AI API key not configured - chat features disabled")
                app_state.llm = None
            else:
                app_state.llm = ChatZAI(
                    model=config.ZAI_MODEL,
                    base_url=config.ZAI_BASE_URL,
                    api_key=config.ZAI_API_KEY,
                )
                logger.info(
                    "LLM initialized (Z.AI)",
                    model=config.ZAI_MODEL,
                    base_url=config.ZAI_BASE_URL,
                )
        else:
            # Default to Ollama
            app_state.llm = ChatOllama(
                model=config.OLLAMA_MODEL,
                base_url=config.OLLAMA_HOST,
            )
            logger.info(
                "LLM initialized (Ollama)",
                model=config.OLLAMA_MODEL,
                host=config.OLLAMA_HOST,
            )
    except Exception as e:
        logger.warning("LLM not available - chat features disabled", error=str(e))
        app_state.llm = None

    # Initialize MCP registry
    app_state.mcp_registry = MCPRegistry()
    app_state.mcp_registry.load(config.REGISTRY_PATH)

    # Initialize MCP client
    app_state.mcp_client = MCPClient(app_state.mcp_registry)

    # Initialize Agent registry
    app_state.agent_registry = AgentRegistry()
    app_state.agent_registry.load(config.REGISTRY_PATH)

    # Initialize Workflow registry
    app_state.workflow_registry = WorkflowRegistry()
    app_state.workflow_registry.load(config.REGISTRY_PATH)

    # Initialize components that need LLM
    if app_state.llm:
        # Router
        app_state.router = Router(app_state.llm)

        # Agent Runtime
        app_state.agent_runtime = AgentRuntime(
            mcp_client=app_state.mcp_client,
            mcp_registry=app_state.mcp_registry,
            agent_registry=app_state.agent_registry,
            llm=app_state.llm,
        )

        # Workflow Engine
        app_state.workflow_engine = WorkflowEngine(
            agent_runtime=app_state.agent_runtime,
            mcp_client=app_state.mcp_client,
        )

        # Planner
        app_state.planner = Planner(
            llm=app_state.llm,
            agents=app_state.agent_registry.as_dict(),
            workflows=app_state.workflow_registry.as_dict(),
        )

        # Orchestrator
        app_state.orchestrator = Orchestrator(
            agent_runtime=app_state.agent_runtime,
            workflow_engine=app_state.workflow_engine,
            workflow_registry=app_state.workflow_registry,
        )

    logger.info(
        "Druppie Governance Platform started",
        mcp_servers=len(app_state.mcp_registry.list_servers()),
        agents=len(app_state.agent_registry.list_agents()),
        workflows=len(app_state.workflow_registry.list_workflows()),
    )

    yield

    # Cleanup
    if app_state.mcp_client:
        await app_state.mcp_client.__aexit__(None, None, None)

    logger.info("Shutting down Druppie Governance Platform")


# --- Application Factory ---


def create_app() -> FastAPI:
    """Create the FastAPI application."""
    app = FastAPI(
        title="Druppie Governance Platform",
        description="AI-powered governance platform with autonomous agents and workflows",
        version="0.3.0",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Health ---

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "version": "0.3.0",
            "llm_available": app_state.llm is not None,
        }

    # --- Chat (Main Interface) ---

    @app.post("/v1/chat/completions", response_model=ChatCompletionResponse)
    async def chat_completions(
        request: ChatCompletionRequest,
        router: Router | None = Depends(get_router),
        planner: Planner | None = Depends(get_planner),
        orchestrator: Orchestrator | None = Depends(get_orchestrator),
        store: FileStore = Depends(get_store),
    ):
        """Main chat interface for the governance platform.

        Flow:
        1. Router analyzes user intent (3 actions: create, update, chat)
        2. If general_chat, respond directly
        3. If clarification needed, ask for more info
        4. Planner selects workflow OR agents
        5. Orchestrator executes the plan
        """
        # Check if LLM is available
        if not router or not planner or not orchestrator:
            if config.LLM_PROVIDER.lower() == "zai":
                error_msg = "LLM is not available. Please check your ZAI_API_KEY in the .env file."
            else:
                error_msg = "LLM is not available. Please start Ollama with: `ollama serve` and pull the model with: `ollama pull qwen2.5:7b`"
            return ChatCompletionResponse(
                id=f"chatcmpl-{uuid.uuid4().hex[:8]}",
                plan_id=f"plan-{uuid.uuid4().hex[:8]}",
                content=error_msg,
                intent=None,
                status="failed",
            )

        # Get user message
        user_messages = [m for m in request.messages if m.role == "user"]
        if not user_messages:
            raise HTTPException(400, "No user message found")

        user_input = user_messages[-1].content
        plan_id = request.plan_id or f"plan-{uuid.uuid4().hex[:8]}"

        # Step 1: Analyze intent
        intent, router_usage = await router.analyze(user_input, plan_id)

        # Step 2: Check if direct response
        if router.is_direct_response(intent):
            plan = Plan(
                id=plan_id,
                name=f"Chat: {intent.prompt[:50]}",
                status=PlanStatus.COMPLETED,
                intent=intent,
            )
            plan.total_usage.add(router_usage)
            await store.save_plan(plan)

            return ChatCompletionResponse(
                id=f"chatcmpl-{uuid.uuid4().hex[:8]}",
                plan_id=plan_id,
                content=intent.answer or "I couldn't generate a response.",
                intent=intent,
                status="completed",
            )

        # Step 3: Check if clarification needed
        if router.needs_clarification(intent):
            plan = Plan(
                id=plan_id,
                name=f"Clarify: {intent.prompt[:50]}",
                status=PlanStatus.PENDING,
                intent=intent,
            )
            plan.total_usage.add(router_usage)
            await store.save_plan(plan)

            return ChatCompletionResponse(
                id=f"chatcmpl-{uuid.uuid4().hex[:8]}",
                plan_id=plan_id,
                content=intent.clarification_question or "Could you provide more details?",
                intent=intent,
                status="clarification_needed",
            )

        # Step 4: Add workspace to project context
        intent.project_context["workspace"] = config.WORKSPACE_PATH

        # Step 5: Create execution plan
        plan, planner_usage = await planner.create_plan(
            plan_id=plan_id,
            intent=intent,
        )
        plan.total_usage.add(router_usage)
        await store.save_plan(plan)

        if plan.status == PlanStatus.FAILED:
            return ChatCompletionResponse(
                id=f"chatcmpl-{uuid.uuid4().hex[:8]}",
                plan_id=plan_id,
                content=f"I couldn't create a plan. {plan.description or ''}",
                intent=intent,
                status="failed",
            )

        # Step 6: Generate response based on plan type
        if plan.plan_type == PlanType.WORKFLOW:
            workflow = app_state.workflow_registry.get_workflow(plan.workflow_id)
            workflow_name = workflow.name if workflow else plan.workflow_id
            response_content = f"""I'll use the **{workflow_name}** workflow to complete your request.

This workflow will:
- Clone/initialize the repository
- Create an appropriate branch
- Write tests (TDD)
- Implement the code
- Run tests and fix any issues
- Push to remote
- Build and test with Docker

The plan is being executed. Check status at `/v1/plans/{plan_id}`"""
        else:
            tasks_summary = "\n".join(
                f"- **{t.agent_id}**: {t.description[:100]}..."
                for t in plan.tasks
            )
            response_content = f"""I've created a plan with {len(plan.tasks)} task(s):

{tasks_summary}

The plan is being executed. Check status at `/v1/plans/{plan_id}`"""

        # Step 7: Execute the plan asynchronously
        # Note: In production, this should be done in a background task
        try:
            plan = await orchestrator.execute(plan)
            await store.save_plan(plan)

            # Build workspace link
            project_name = intent.project_context.get("project_name", "").replace(" ", "_")
            workspace_link = f"/v1/workspace?path={project_name}" if project_name else "/v1/workspace"

            if plan.status == PlanStatus.COMPLETED:
                # Get summary from results
                if plan.plan_type == PlanType.WORKFLOW and plan.workflow_run:
                    summary = plan.workflow_run.context.get("step_complete", {}).get(
                        "summary", "Workflow completed successfully"
                    )
                elif plan.tasks and plan.tasks[-1].result:
                    summary = plan.tasks[-1].result.summary
                else:
                    summary = "Plan completed successfully"

                response_content = f"""**Plan completed!**

{summary}

**View your files:**
- Browse workspace: [{workspace_link}]({workspace_link})
- Workspace path: `{config.WORKSPACE_PATH}/{project_name}`

View full details at `/v1/plans/{plan_id}`"""
            elif plan.status == PlanStatus.FAILED:
                # Still show workspace link for partial results
                response_content = f"""**Plan failed.**

Some files may have been created. Check:
- Workspace: [{workspace_link}]({workspace_link})

Check details at `/v1/plans/{plan_id}`"""

        except Exception as e:
            logger.error("Plan execution failed", plan_id=plan_id, error=str(e))
            plan.status = PlanStatus.FAILED
            await store.save_plan(plan)
            response_content = f"""**Execution error**: {str(e)}

Check workspace for any partial results: `/v1/workspace`

Check details at `/v1/plans/{plan_id}`"""

        return ChatCompletionResponse(
            id=f"chatcmpl-{uuid.uuid4().hex[:8]}",
            plan_id=plan_id,
            content=response_content,
            intent=intent,
            status=plan.status.value,
        )

    # --- Agents ---

    @app.get("/v1/agents")
    async def list_agents(
        registry: AgentRegistry = Depends(get_agent_registry),
    ):
        """List available agents."""
        agents = registry.list_agents()
        return [
            {
                "id": a.id,
                "name": a.name,
                "type": a.type.value,
                "description": a.description,
                "mcps": a.mcps,
                "max_iterations": a.max_iterations,
            }
            for a in agents
        ]

    @app.get("/v1/agents/{agent_id}")
    async def get_agent(
        agent_id: str,
        registry: AgentRegistry = Depends(get_agent_registry),
    ):
        """Get an agent by ID."""
        agent = registry.get_agent(agent_id)
        if not agent:
            raise HTTPException(404, "Agent not found")
        return agent.model_dump()

    # --- Workflows ---

    @app.get("/v1/workflows")
    async def list_workflows(
        registry: WorkflowRegistry = Depends(get_workflow_registry),
    ):
        """List available workflows."""
        workflows = registry.list_workflows()
        return [
            {
                "id": w.id,
                "name": w.name,
                "description": w.description,
                "trigger_keywords": w.trigger_keywords,
                "required_mcps": w.required_mcps,
                "num_steps": len(w.steps),
            }
            for w in workflows
        ]

    @app.get("/v1/workflows/{workflow_id}")
    async def get_workflow(
        workflow_id: str,
        registry: WorkflowRegistry = Depends(get_workflow_registry),
    ):
        """Get a workflow by ID."""
        workflow = registry.get_workflow(workflow_id)
        if not workflow:
            raise HTTPException(404, "Workflow not found")
        return workflow.model_dump()

    # --- Plans ---

    @app.get("/v1/plans")
    async def list_plans(
        status: str | None = None,
        limit: int = 100,
        store: FileStore = Depends(get_store),
    ):
        """List execution plans."""
        return await store.list_plans(status=status, limit=limit)

    @app.get("/v1/plans/{plan_id}")
    async def get_plan(
        plan_id: str,
        store: FileStore = Depends(get_store),
    ):
        """Get a plan by ID."""
        plan = await store.get_plan(plan_id)
        if not plan:
            raise HTTPException(404, "Plan not found")
        return plan.model_dump()

    @app.delete("/v1/plans/{plan_id}")
    async def delete_plan(
        plan_id: str,
        store: FileStore = Depends(get_store),
    ):
        """Delete a plan."""
        if not await store.delete_plan(plan_id):
            raise HTTPException(404, "Plan not found")
        return {"status": "deleted"}

    # --- Tasks (Pending Approvals) ---

    @app.get("/v1/tasks")
    async def list_tasks(
        store: FileStore = Depends(get_store),
    ):
        """List pending tasks that need approval.

        In the new architecture, tasks requiring human approval are tracked
        within plans. This endpoint returns all pending tasks from active plans.
        """
        # Get all running/pending plans
        plans = await store.list_plans(limit=100)
        tasks = []

        for plan in plans:
            plan_id = plan.id
            plan_status = plan.status.value if hasattr(plan.status, 'value') else plan.status

            # Only include tasks from active plans
            if plan_status not in ["pending", "running"]:
                continue

            # Collect pending tasks
            for i, task in enumerate(plan.tasks):
                task_status = task.status.value if hasattr(task.status, 'value') else task.status
                if task_status == "pending":
                    tasks.append({
                        "plan_id": plan_id,
                        "step_id": i,
                        "task_id": task.id,
                        "action": task.description[:100],
                        "agent_id": task.agent_id,
                        "assigned_group": None,  # Could be extended for RBAC
                    })

        return tasks

    @app.post("/v1/tasks/{plan_id}/{step_id}/approve")
    async def approve_task(
        plan_id: str,
        step_id: int,
        store: FileStore = Depends(get_store),
    ):
        """Approve a pending task."""
        plan = await store.get_plan(plan_id)
        if not plan:
            raise HTTPException(404, "Plan not found")

        if step_id >= len(plan.tasks):
            raise HTTPException(404, "Task not found")

        # In the new architecture, tasks auto-execute
        # This endpoint is for future human-in-the-loop approval
        return {"status": "approved", "message": "Task approval noted"}

    @app.post("/v1/tasks/{plan_id}/{step_id}/reject")
    async def reject_task(
        plan_id: str,
        step_id: int,
        reason: str = "",
        store: FileStore = Depends(get_store),
    ):
        """Reject a pending task."""
        plan = await store.get_plan(plan_id)
        if not plan:
            raise HTTPException(404, "Plan not found")

        if step_id >= len(plan.tasks):
            raise HTTPException(404, "Task not found")

        # In the new architecture, tasks auto-execute
        # This endpoint is for future human-in-the-loop rejection
        return {"status": "rejected", "reason": reason}

    # --- MCP ---

    @app.get("/v1/mcp/servers")
    async def list_mcp_servers(
        registry: MCPRegistry = Depends(get_mcp_registry),
    ):
        """List registered MCP servers."""
        servers = registry.list_servers()
        return [
            {
                "id": s.id,
                "name": s.name,
                "description": s.description,
                "transport": s.transport,
                "tools": len(s.tools),
            }
            for s in servers
        ]

    @app.get("/v1/mcp/tools")
    async def list_mcp_tools(
        registry: MCPRegistry = Depends(get_mcp_registry),
    ):
        """List all available MCP tools."""
        return registry.list_tools()

    @app.post("/v1/mcp/invoke")
    async def invoke_mcp_tool(
        tool_name: str,
        arguments: dict[str, Any] = {},
        client: MCPClient = Depends(get_mcp_client),
    ):
        """Invoke an MCP tool directly (for testing)."""
        try:
            result = await client.invoke(tool_name, arguments)
            return {"result": result}
        except Exception as e:
            raise HTTPException(500, str(e))

    # --- Workspace Files (View Created Files) ---

    @app.get("/v1/workspace")
    async def list_workspace_files(
        path: str = "",
        plan_id: str | None = None,
        store: FileStore = Depends(get_store),
    ):
        """List files in the workspace directory.

        Args:
            path: Relative path within workspace
            plan_id: Optional plan ID to get plan-specific workspace
        """
        workspace = Path(config.WORKSPACE_PATH)

        # If plan_id provided, get plan's project workspace
        plan_info = None
        project_name = ""
        if plan_id:
            plan = await store.get_plan(plan_id)
            if plan:
                # Use project name from plan context as subdirectory
                project_name = plan.project_context.get("project_name", "").replace(" ", "_")
                plan_info = {
                    "id": plan.id,
                    "name": plan.name,
                    "status": plan.status.value if hasattr(plan.status, 'value') else plan.status,
                    "project_name": project_name,  # Include for frontend path construction
                }
                if project_name:
                    workspace = workspace / project_name

        target = workspace / path if path else workspace

        if not target.exists():
            # Create the workspace directory if it doesn't exist
            workspace.mkdir(parents=True, exist_ok=True)
            return {
                "path": path,
                "workspace": str(workspace),
                "plan": plan_info,
                "files": [],
                "directories": [],
            }

        if not str(target.resolve()).startswith(str(Path(config.WORKSPACE_PATH).resolve())):
            raise HTTPException(403, "Access denied")

        files = []
        directories = []

        try:
            for item in sorted(target.iterdir()):
                rel_path = str(item.relative_to(workspace))
                if item.is_dir():
                    directories.append({
                        "name": item.name,
                        "path": rel_path,
                        "type": "directory",
                    })
                else:
                    files.append({
                        "name": item.name,
                        "path": rel_path,
                        "type": "file",
                        "size": item.stat().st_size,
                    })
        except PermissionError:
            pass

        return {
            "path": path,
            "workspace": str(workspace),
            "plan": plan_info,
            "files": files,
            "directories": directories,
        }

    @app.get("/v1/workspace/plans")
    async def list_workspace_plans(
        store: FileStore = Depends(get_store),
    ):
        """List plans with their workspace information."""
        plans = await store.list_plans(limit=100)
        result = []

        for plan in plans:
            project_name = plan.project_context.get("project_name", "").replace(" ", "_")
            workspace_path = Path(config.WORKSPACE_PATH) / project_name if project_name else Path(config.WORKSPACE_PATH)

            # Check if workspace has files
            file_count = 0
            if workspace_path.exists():
                try:
                    file_count = sum(1 for _ in workspace_path.rglob("*") if _.is_file())
                except:
                    pass

            result.append({
                "plan_id": plan.id,
                "name": plan.name,
                "project_name": project_name,
                "status": plan.status.value if hasattr(plan.status, 'value') else plan.status,
                "workspace_path": str(workspace_path),
                "file_count": file_count,
                "created_at": plan.created_at.isoformat() if plan.created_at else None,
            })

        return result

    @app.get("/v1/workspace/file")
    async def get_workspace_file(
        path: str,
    ):
        """Get content of a file in the workspace."""
        workspace = Path(config.WORKSPACE_PATH)
        target = workspace / path

        if not target.exists():
            raise HTTPException(404, "File not found")

        if not str(target.resolve()).startswith(str(workspace.resolve())):
            raise HTTPException(403, "Access denied")

        if target.is_dir():
            raise HTTPException(400, "Path is a directory")

        # Check file size (limit to 1MB for text viewing)
        if target.stat().st_size > 1024 * 1024:
            raise HTTPException(400, "File too large to display")

        try:
            content = target.read_text()
            return {
                "path": path,
                "content": content,
                "size": len(content),
            }
        except UnicodeDecodeError:
            # Binary file
            return {
                "path": path,
                "content": None,
                "binary": True,
                "size": target.stat().st_size,
            }

    @app.get("/v1/workspace/download")
    async def download_workspace_file(
        path: str,
    ):
        """Download a file from the workspace."""
        workspace = Path(config.WORKSPACE_PATH)
        target = workspace / path

        if not target.exists():
            raise HTTPException(404, "File not found")

        if not str(target.resolve()).startswith(str(workspace.resolve())):
            raise HTTPException(403, "Access denied")

        if target.is_dir():
            raise HTTPException(400, "Cannot download directory")

        return FileResponse(target, filename=target.name)

    @app.post("/v1/generate")
    async def generate_code(
        request: dict[str, Any],
        store: FileStore = Depends(get_store),
    ):
        """Generate code directly using LLM and save to workspace.

        This is a simpler alternative to the full workflow - it generates
        code directly and saves files without complex agent orchestration.
        """
        if not app_state.llm:
            raise HTTPException(500, "LLM not available")

        task = request.get("task", "")
        project_name = request.get("project_name", "project").replace(" ", "_")

        # Create project directory
        project_dir = Path(config.WORKSPACE_PATH) / project_name
        project_dir.mkdir(parents=True, exist_ok=True)

        # Generate code using LLM
        prompt = f"""Generate code for the following task. Return ONLY valid JSON with this structure:
{{
    "files": [
        {{"path": "filename.py", "content": "file content here"}},
        {{"path": "test_filename.py", "content": "test content here"}}
    ],
    "summary": "Brief description of what was created",
    "run_command": "Command to run the code"
}}

Task: {task}

Requirements:
- Create working, complete code
- Include a main file and tests if applicable
- Use appropriate file extensions
- Include a README.md with usage instructions
"""

        from langchain_core.messages import HumanMessage, SystemMessage
        messages = [
            SystemMessage(content="You are a code generator. Generate complete, working code. Return ONLY valid JSON, no markdown."),
            HumanMessage(content=prompt),
        ]

        try:
            response = await app_state.llm.ainvoke(messages)
            content = response.content

            # Parse JSON from response
            import re
            json_match = re.search(r'\{[\s\S]*\}', content)
            if not json_match:
                raise ValueError("No JSON found in response")

            data = json.loads(json_match.group())

            # Create files
            created_files = []
            for file_info in data.get("files", []):
                file_path = project_dir / file_info["path"]
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(file_info["content"])
                created_files.append(str(file_path.relative_to(Path(config.WORKSPACE_PATH))))

            # Create a plan record for this generation
            plan_id = f"plan-{uuid.uuid4().hex[:8]}"
            from druppie.core.models import Intent, IntentAction
            plan = Plan(
                id=plan_id,
                name=f"Generate: {project_name}",
                status=PlanStatus.COMPLETED,
                plan_type=PlanType.AGENTS,
                intent=Intent(
                    initial_prompt=task,
                    prompt=task,
                    action=IntentAction.CREATE_PROJECT,
                    project_context={"project_name": project_name},
                ),
                project_context={"project_name": project_name},
            )
            await store.save_plan(plan)

            return {
                "success": True,
                "plan_id": plan_id,
                "project_name": project_name,
                "files": created_files,
                "summary": data.get("summary", "Code generated"),
                "run_command": data.get("run_command", ""),
                "workspace": str(project_dir),
            }

        except Exception as e:
            logger.error("Code generation failed", error=str(e))
            raise HTTPException(500, f"Generation failed: {str(e)}")

    # --- Static Files (UI) ---

    @app.get("/")
    async def serve_ui():
        """Serve the web UI."""
        static_path = (
            Path(__file__).parent.parent.parent.parent / "static" / "index.html"
        )
        if static_path.exists():
            return FileResponse(static_path)
        raise HTTPException(404, "UI not found")

    # Mount static files
    static_dir = Path(__file__).parent.parent.parent.parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    return app


# For running directly with uvicorn
app = create_app()

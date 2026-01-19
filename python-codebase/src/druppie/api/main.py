"""FastAPI application for Druppie Governance Platform.

Provides REST API for:
- Chat: Main interface for AI interaction (Router → Planner → Executor)
- Plans: Create, read, update, delete execution plans
- Agents: List available agents
- MCP: List available tools
- Tasks: Human-in-the-loop approvals
"""

import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any
import uuid

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import structlog

from langchain_ollama import ChatOllama
from druppie.llm import ChatZAI

# Load .env file from project root
load_dotenv(Path(__file__).parent.parent.parent.parent / ".env")

from druppie.core.models import (
    Plan,
    PlanStatus,
    Step,
    StepStatus,
    FeedbackItem,
    ChatMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    Intent,
    AgentDefinition,
)
from druppie.mcp import MCPRegistry, MCPClient
from druppie.store import FileStore
from druppie.router import Router
from druppie.planner import Planner
from druppie.registry import AgentRegistry
from druppie.executor import Dispatcher, create_default_dispatcher
from druppie.task_manager import TaskManager

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
    ZAI_BASE_URL: str = os.getenv("ZAI_BASE_URL", "https://api.z.ai/api/coding/paas/v4")

    # Registry
    REGISTRY_PATH: str = os.getenv("REGISTRY_PATH", "registry")


config = Config()


# --- Request/Response Models ---


class CreatePlanRequest(BaseModel):
    """Request to create a new plan."""

    name: str
    description: str | None = None
    input_data: dict[str, Any] = {}


class SubmitFeedbackRequest(BaseModel):
    """Request to submit feedback on a plan."""

    step_id: int | None = None
    feedback_type: str
    comment: str | None = None
    expected_output: dict[str, Any] | None = None


class ApproveTaskRequest(BaseModel):
    """Request to approve a task."""

    user: str = "anonymous"
    comment: str | None = None


class RejectTaskRequest(BaseModel):
    """Request to reject a task."""

    user: str = "anonymous"
    reason: str = ""


# --- Application State ---


class AppState:
    """Application state container."""

    def __init__(self):
        self.store: FileStore | None = None
        self.mcp_registry: MCPRegistry | None = None
        self.mcp_client: MCPClient | None = None
        self.agent_registry: AgentRegistry | None = None
        self.llm = None
        self.router: Router | None = None
        self.planner: Planner | None = None
        self.dispatcher: Dispatcher | None = None
        self.task_manager: TaskManager | None = None


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


def get_router() -> Router | None:
    return app_state.router


def get_planner() -> Planner | None:
    return app_state.planner


def get_task_manager() -> TaskManager:
    if not app_state.task_manager:
        raise HTTPException(500, "Task Manager not initialized")
    return app_state.task_manager


# --- Lifespan ---


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("Starting Druppie Governance Platform")

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

    # Initialize Router and Planner (if LLM available)
    if app_state.llm:
        app_state.router = Router(app_state.llm)
        app_state.planner = Planner(
            llm=app_state.llm,
            agents=app_state.agent_registry.as_dict(),
        )
    else:
        app_state.router = None
        app_state.planner = None

    # Initialize Dispatcher with executors
    app_state.dispatcher = create_default_dispatcher()

    # Set LLM on executors that need it
    for executor in app_state.dispatcher.executors:
        if hasattr(executor, "set_llm"):
            executor.set_llm(app_state.llm)
        if hasattr(executor, "set_client"):
            executor.set_client(app_state.mcp_client)
        if hasattr(executor, "set_available_tools"):
            tools = [t["name"] for t in app_state.mcp_registry.list_tools()]
            executor.set_available_tools(tools)

    # Initialize Task Manager
    app_state.task_manager = TaskManager(
        dispatcher=app_state.dispatcher,
        store=app_state.store,
    )

    logger.info(
        "Druppie Governance Platform started",
        mcp_servers=len(app_state.mcp_registry.list_servers()),
        agents=len(app_state.agent_registry.list_agents()),
    )

    yield

    logger.info("Shutting down Druppie Governance Platform")


# --- Application Factory ---


def create_app() -> FastAPI:
    """Create the FastAPI application."""
    app = FastAPI(
        title="Druppie Governance Platform",
        description="AI-powered governance platform for building solutions",
        version="0.2.0",
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
        return {"status": "ok", "version": "0.2.0"}

    # --- Chat (Main Interface) ---

    @app.post("/v1/chat/completions", response_model=ChatCompletionResponse)
    async def chat_completions(
        request: ChatCompletionRequest,
        router: Router | None = Depends(get_router),
        planner: Planner | None = Depends(get_planner),
        task_manager: TaskManager = Depends(get_task_manager),
        store: FileStore = Depends(get_store),
        mcp_registry: MCPRegistry = Depends(get_mcp_registry),
    ):
        """Main chat interface for the governance platform.

        Flow:
        1. Router analyzes user intent
        2. If general_chat, respond directly
        3. Otherwise, Planner creates execution plan
        4. Task Manager executes the plan
        """
        # Check if LLM is available
        if not router or not planner:
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
            # Create minimal plan for tracking
            plan = Plan(
                id=plan_id,
                name=f"Chat: {intent.prompt[:50]}",
                status=PlanStatus.COMPLETED,
                intent=intent,
                steps=[],
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

        # Step 3: Create execution plan
        available_tools = [t["name"] for t in mcp_registry.list_tools()]
        plan, planner_usage = await planner.create_plan(
            plan_id=plan_id,
            intent=intent,
            available_tools=available_tools,
        )
        plan.total_usage.add(router_usage)
        await store.save_plan(plan)

        if plan.status == PlanStatus.FAILED or not plan.steps:
            return ChatCompletionResponse(
                id=f"chatcmpl-{uuid.uuid4().hex[:8]}",
                plan_id=plan_id,
                content=f"I created a plan but couldn't generate steps. {plan.description or ''}",
                intent=intent,
                status="failed",
            )

        # Step 4: Start execution
        output_messages = []

        def capture_output(msg: str):
            output_messages.append(msg)

        task = await task_manager.start_task(
            plan=plan,
            context={"project_path": plan.project_path},
            output_callback=capture_output,
        )

        # Generate response based on plan
        steps_summary = "\n".join(
            f"- Step {s.id}: [{s.agent_id}] {s.action}"
            for s in plan.steps
        )

        response_content = f"""I've created an execution plan with {len(plan.steps)} steps:

{steps_summary}

The plan is now being executed. You can check the status at /v1/plans/{plan_id}"""

        return ChatCompletionResponse(
            id=f"chatcmpl-{uuid.uuid4().hex[:8]}",
            plan_id=plan_id,
            content=response_content,
            intent=intent,
            status="executing",
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
                "skills": a.skills,
                "priority": a.priority,
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

    # --- Plans ---

    @app.post("/v1/plans", response_model=Plan)
    async def create_plan(
        request: CreatePlanRequest,
        store: FileStore = Depends(get_store),
    ):
        """Create a new execution plan manually."""
        plan = Plan(
            id=f"plan-{uuid.uuid4().hex[:8]}",
            name=request.name,
            description=request.description,
            input_data=request.input_data,
        )

        await store.save_plan(plan)
        logger.info("Plan created", plan_id=plan.id)

        return plan

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

    @app.post("/v1/plans/{plan_id}/feedback")
    async def submit_feedback(
        plan_id: str,
        request: SubmitFeedbackRequest,
        store: FileStore = Depends(get_store),
    ):
        """Submit feedback on a plan execution."""
        plan = await store.get_plan(plan_id)
        if not plan:
            raise HTTPException(404, "Plan not found")

        feedback = FeedbackItem(
            id=f"fb-{uuid.uuid4().hex[:8]}",
            step_id=request.step_id,
            feedback_type=request.feedback_type,
            comment=request.comment,
            expected_output=request.expected_output,
        )

        plan.feedback.append(feedback)
        await store.save_plan(plan)

        logger.info("Feedback submitted", plan_id=plan_id, feedback_id=feedback.id)

        return feedback.model_dump()

    @app.post("/v1/plans/{plan_id}/cancel")
    async def cancel_plan(
        plan_id: str,
        task_manager: TaskManager = Depends(get_task_manager),
    ):
        """Cancel a running plan."""
        if await task_manager.cancel_task(plan_id):
            return {"status": "cancelled"}
        raise HTTPException(404, "Plan not found or not running")

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

    # --- Tasks (Human-in-the-loop) ---

    @app.get("/v1/tasks")
    async def list_pending_tasks(
        task_manager: TaskManager = Depends(get_task_manager),
        store: FileStore = Depends(get_store),
    ):
        """List tasks waiting for human input."""
        # Get from task manager
        pending = task_manager.get_pending_tasks()
        tasks = []

        for task in pending:
            for step in task.plan.steps:
                if step.status == StepStatus.WAITING_INPUT:
                    tasks.append(
                        {
                            "plan_id": task.plan.id,
                            "plan_name": task.plan.name,
                            "step_id": step.id,
                            "action": step.action,
                            "agent_id": step.agent_id,
                            "assigned_group": step.assigned_group,
                            "params": step.params,
                        }
                    )

        # Also check stored plans
        stored_plans = await store.list_plans(status=PlanStatus.WAITING_INPUT.value)
        for plan in stored_plans:
            if plan.id not in [t.id for t in pending]:
                for step in plan.steps:
                    if step.status == StepStatus.WAITING_INPUT:
                        tasks.append(
                            {
                                "plan_id": plan.id,
                                "plan_name": plan.name,
                                "step_id": step.id,
                                "action": step.action,
                                "agent_id": step.agent_id,
                                "assigned_group": step.assigned_group,
                                "params": step.params,
                            }
                        )

        return tasks

    @app.post("/v1/tasks/{plan_id}/{step_id}/approve")
    async def approve_task(
        plan_id: str,
        step_id: int,
        request: ApproveTaskRequest,
        task_manager: TaskManager = Depends(get_task_manager),
        store: FileStore = Depends(get_store),
    ):
        """Approve a pending task."""
        # Try task manager first (running task)
        if await task_manager.submit_input(
            task_id=plan_id,
            step_id=step_id,
            input_data={"approved": True, "user": request.user},
        ):
            return {"status": "approved"}

        # Fallback to stored plan
        plan = await store.get_plan(plan_id)
        if not plan:
            raise HTTPException(404, "Plan not found")

        for step in plan.steps:
            if step.id == step_id:
                step.status = StepStatus.COMPLETED
                step.approved_by = request.user
                step.completed_at = datetime.utcnow()
                break
        else:
            raise HTTPException(404, "Step not found")

        # Check if all steps are done
        all_done = all(
            s.status in (StepStatus.COMPLETED, StepStatus.SKIPPED) for s in plan.steps
        )
        if all_done:
            plan.status = PlanStatus.COMPLETED

        await store.save_plan(plan)
        logger.info("Task approved", plan_id=plan_id, step_id=step_id)

        return {"status": "approved"}

    @app.post("/v1/tasks/{plan_id}/{step_id}/reject")
    async def reject_task(
        plan_id: str,
        step_id: int,
        request: RejectTaskRequest,
        task_manager: TaskManager = Depends(get_task_manager),
        store: FileStore = Depends(get_store),
    ):
        """Reject a pending task."""
        # Try task manager first
        if await task_manager.submit_input(
            task_id=plan_id,
            step_id=step_id,
            input_data={"approved": False, "user": request.user, "reason": request.reason},
        ):
            return {"status": "rejected"}

        # Fallback to stored plan
        plan = await store.get_plan(plan_id)
        if not plan:
            raise HTTPException(404, "Plan not found")

        for step in plan.steps:
            if step.id == step_id:
                step.status = StepStatus.FAILED
                step.error = request.reason
                step.completed_at = datetime.utcnow()
                break
        else:
            raise HTTPException(404, "Step not found")

        plan.status = PlanStatus.FAILED
        await store.save_plan(plan)

        logger.info("Task rejected", plan_id=plan_id, step_id=step_id, reason=request.reason)

        return {"status": "rejected"}

    # --- Static Files (UI) ---

    # Serve index.html at root
    @app.get("/")
    async def serve_ui():
        """Serve the web UI."""
        static_path = Path(__file__).parent.parent.parent.parent / "static" / "index.html"
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

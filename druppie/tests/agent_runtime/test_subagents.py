"""Tests for druppie.agent_runtime.subagents."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from druppie.agent_runtime.definition import AgentDefinition
from druppie.agent_runtime.subagents import SubagentsMCP
from druppie.agent_runtime.tools.mcp import MCPConnection
from druppie.agent_runtime.types import AgentResult, LoopConfig


def _make_agent(
    agent_id: str,
    description: str = "desc",
    subagents: list[str] | None = None,
    sandbox_git: str | None = None,
    role: str = "primary",
) -> AgentDefinition:
    mcps = {}
    if sandbox_git:
        mcps["sandbox"] = {"tools": ["read_file"], "git": sandbox_git}
    return AgentDefinition(
        id=agent_id,
        name=agent_id.title(),
        description=description,
        system_prompt=f"You are {agent_id}.",
        role=role,
        subagents=subagents or [],
        mcps=mcps,
    )


def _make_agent_loader(agent_map: dict[str, AgentDefinition]):
    def loader(agent_id: str) -> AgentDefinition:
        if agent_id in agent_map:
            return agent_map[agent_id]
        raise ValueError(f"Unknown agent: {agent_id}")
    return loader


def _make_loop_runner(results: dict[str, AgentResult] | None = None):
    default_result = AgentResult(status="completed", done_result={"summary": "ok"})
    results = results or {}

    async def runner(**kwargs) -> AgentResult:
        agent: AgentDefinition = kwargs["agent"]
        return results.get(agent.id, default_result)

    return runner


class TestBuildSchema:
    def test_build_schema_single_agent(self):
        planner = _make_agent("coding_planner", "Creates plans")
        mcp = SubagentsMCP(agent_loader=_make_agent_loader({"coding_planner": planner}))
        schema = mcp.build_schema(["coding_planner"])

        assert schema["name"] == "subagents"
        enum = schema["inputSchema"]["properties"]["agents"]["items"]["properties"]["agent"]["enum"]
        assert enum == ["coding_planner"]

    def test_build_schema_multiple_agents(self):
        a = _make_agent("builder", "Builds")
        b = _make_agent("tester", "Tests")
        mcp = SubagentsMCP(agent_loader=_make_agent_loader({"builder": a, "tester": b}))
        schema = mcp.build_schema(["builder", "tester"])

        enum = schema["inputSchema"]["properties"]["agents"]["items"]["properties"]["agent"]["enum"]
        assert "builder" in enum
        assert "tester" in enum

    def test_build_schema_includes_descriptions(self):
        planner = _make_agent("coding_planner", "Creates detailed plans")
        mcp = SubagentsMCP(agent_loader=_make_agent_loader({"coding_planner": planner}))
        schema = mcp.build_schema(["coding_planner"])

        assert "coding_planner: Creates detailed plans" in schema["description"]

    def test_build_schema_missing_agent_graceful(self):
        mcp = SubagentsMCP(agent_loader=_make_agent_loader({}))
        schema = mcp.build_schema(["unknown_agent"])

        assert "- unknown_agent" in schema["description"]
        assert "unknown_agent" not in schema["description"].split("\n")[0]

    def test_build_schema_required_fields(self):
        a = _make_agent("x", "X agent")
        mcp = SubagentsMCP(agent_loader=_make_agent_loader({"x": a}))
        schema = mcp.build_schema(["x"])

        assert "agents" in schema["inputSchema"]["required"]
        item_props = schema["inputSchema"]["properties"]["agents"]["items"]
        assert "agent" in item_props["required"]
        assert "prompt" in item_props["required"]


class TestExecute:
    @pytest.mark.asyncio
    async def test_execute_single_subagent(self):
        builder = _make_agent("builder", "Builds things")
        parent = _make_agent("dev", "Dev", subagents=["builder"])
        mcp = SubagentsMCP(
            agent_loader=_make_agent_loader({"builder": builder}),
            loop_runner=_make_loop_runner(),
        )

        results = await mcp.execute(
            agents=[{"agent": "builder", "prompt": "build it"}],
            parent_agent=parent,
            parent_tool_provider=MagicMock(),
            parent_git_scope=None,
            parent_sandbox_conn=None,
            llm=AsyncMock(),
            config=LoopConfig(),
        )

        assert len(results) == 1
        assert results[0]["agent"] == "builder"
        assert results[0]["status"] == "success"
        assert results[0]["result"].status == "completed"
        assert results[0]["error"] is None

    @pytest.mark.asyncio
    async def test_execute_multiple_subagents_parallel(self):
        builder = _make_agent("builder", "Builds")
        tester = _make_agent("tester", "Tests")
        parent = _make_agent("dev", "Dev", subagents=["builder", "tester"])
        mcp = SubagentsMCP(
            agent_loader=_make_agent_loader({"builder": builder, "tester": tester}),
            loop_runner=_make_loop_runner(),
        )

        results = await mcp.execute(
            agents=[
                {"agent": "builder", "prompt": "build"},
                {"agent": "tester", "prompt": "test"},
            ],
            parent_agent=parent,
            parent_tool_provider=MagicMock(),
            parent_git_scope=None,
            parent_sandbox_conn=None,
            llm=AsyncMock(),
            config=LoopConfig(),
        )

        assert len(results) == 2
        assert all(r["status"] == "success" for r in results)

    @pytest.mark.asyncio
    async def test_execute_agent_not_in_allowed_list(self):
        parent = _make_agent("dev", "Dev", subagents=["builder"])
        mcp = SubagentsMCP(
            agent_loader=_make_agent_loader({}),
            loop_runner=_make_loop_runner(),
        )

        results = await mcp.execute(
            agents=[{"agent": "unknown", "prompt": "do stuff"}],
            parent_agent=parent,
            parent_tool_provider=MagicMock(),
            parent_git_scope=None,
            parent_sandbox_conn=None,
            llm=AsyncMock(),
            config=LoopConfig(),
        )

        assert len(results) == 1
        assert results[0]["status"] == "error"
        assert "not in allowed subagents list" in results[0]["error"]
        assert results[0]["result"] is None

    @pytest.mark.asyncio
    async def test_role_enforcement_subagent_only_at_top_level(self):
        child = _make_agent("internal", "Internal", role="subagent")
        parent = _make_agent("dev", "Dev", subagents=["internal"])
        mcp = SubagentsMCP(
            agent_loader=_make_agent_loader({"internal": child}),
            loop_runner=_make_loop_runner(),
        )

        results = await mcp.execute(
            agents=[{"agent": "internal", "prompt": "do work"}],
            parent_agent=parent,
            parent_tool_provider=MagicMock(),
            parent_git_scope=None,
            parent_sandbox_conn=None,
            llm=AsyncMock(),
            config=LoopConfig(),
            current_depth=0,
        )

        assert results[0]["status"] == "error"
        assert "subagent-only" in results[0]["error"]

    @pytest.mark.asyncio
    async def test_role_enforcement_subagent_allowed_at_depth(self):
        child = _make_agent("internal", "Internal", role="subagent")
        parent = _make_agent("dev", "Dev", subagents=["internal"])
        mcp = SubagentsMCP(
            agent_loader=_make_agent_loader({"internal": child}),
            loop_runner=_make_loop_runner(),
        )

        results = await mcp.execute(
            agents=[{"agent": "internal", "prompt": "do work"}],
            parent_agent=parent,
            parent_tool_provider=MagicMock(),
            parent_git_scope=None,
            parent_sandbox_conn=None,
            llm=AsyncMock(),
            config=LoopConfig(),
            current_depth=1,
        )

        assert results[0]["status"] == "success"

    @pytest.mark.asyncio
    async def test_depth_limit_exceeded(self):
        child = _make_agent("builder", "Builds")
        parent = _make_agent("dev", "Dev", subagents=["builder"])
        config = LoopConfig(max_subagent_depth=2)
        mcp = SubagentsMCP(
            agent_loader=_make_agent_loader({"builder": child}),
            loop_runner=_make_loop_runner(),
        )

        results = await mcp.execute(
            agents=[{"agent": "builder", "prompt": "build"}],
            parent_agent=parent,
            parent_tool_provider=MagicMock(),
            parent_git_scope=None,
            parent_sandbox_conn=None,
            llm=AsyncMock(),
            config=config,
            current_depth=2,
        )

        assert results[0]["status"] == "error"
        assert "Maximum subagent depth" in results[0]["error"]

    @pytest.mark.asyncio
    async def test_circular_reference_detection(self):
        child = _make_agent("dev", "Dev")
        parent = _make_agent("dev", "Dev", subagents=["dev"])
        mcp = SubagentsMCP(
            agent_loader=_make_agent_loader({"dev": child}),
            loop_runner=_make_loop_runner(),
        )

        results = await mcp.execute(
            agents=[{"agent": "dev", "prompt": " recurse"}],
            parent_agent=parent,
            parent_tool_provider=MagicMock(),
            parent_git_scope=None,
            parent_sandbox_conn=None,
            llm=AsyncMock(),
            config=LoopConfig(),
            agent_chain=["dev"],
        )

        assert results[0]["status"] == "error"
        assert "Circular reference" in results[0]["error"]

    @pytest.mark.asyncio
    async def test_no_loop_runner(self):
        child = _make_agent("builder", "Builds")
        parent = _make_agent("dev", "Dev", subagents=["builder"])
        mcp = SubagentsMCP(
            agent_loader=_make_agent_loader({"builder": child}),
            loop_runner=None,
        )

        results = await mcp.execute(
            agents=[{"agent": "builder", "prompt": "build"}],
            parent_agent=parent,
            parent_tool_provider=MagicMock(),
            parent_git_scope=None,
            parent_sandbox_conn=None,
            llm=AsyncMock(),
            config=LoopConfig(),
        )

        assert results[0]["status"] == "error"
        assert "No loop runner" in results[0]["error"]

    @pytest.mark.asyncio
    async def test_loop_runner_exception(self):
        child = _make_agent("builder", "Builds")
        parent = _make_agent("dev", "Dev", subagents=["builder"])

        async def failing_runner(**kwargs):
            raise RuntimeError("LLM timeout")

        mcp = SubagentsMCP(
            agent_loader=_make_agent_loader({"builder": child}),
            loop_runner=failing_runner,
        )

        results = await mcp.execute(
            agents=[{"agent": "builder", "prompt": "build"}],
            parent_agent=parent,
            parent_tool_provider=MagicMock(),
            parent_git_scope=None,
            parent_sandbox_conn=None,
            llm=AsyncMock(),
            config=LoopConfig(),
        )

        assert results[0]["status"] == "error"
        assert "LLM timeout" in results[0]["error"]

    @pytest.mark.asyncio
    async def test_agent_loader_failure(self):
        parent = _make_agent("dev", "Dev", subagents=["broken"])
        mcp = SubagentsMCP(
            agent_loader=_make_agent_loader({}),
            loop_runner=_make_loop_runner(),
        )

        results = await mcp.execute(
            agents=[{"agent": "broken", "prompt": "build"}],
            parent_agent=parent,
            parent_tool_provider=MagicMock(),
            parent_git_scope=None,
            parent_sandbox_conn=None,
            llm=AsyncMock(),
            config=LoopConfig(),
        )

        assert results[0]["status"] == "error"
        assert "Failed to load agent" in results[0]["error"]

    @pytest.mark.asyncio
    async def test_partial_failure(self):
        builder = _make_agent("builder", "Builds")
        parent = _make_agent("dev", "Dev", subagents=["builder", "unknown"])
        mcp = SubagentsMCP(
            agent_loader=_make_agent_loader({"builder": builder}),
            loop_runner=_make_loop_runner(),
        )

        results = await mcp.execute(
            agents=[
                {"agent": "builder", "prompt": "build"},
                {"agent": "unknown", "prompt": "fail"},
            ],
            parent_agent=parent,
            parent_tool_provider=MagicMock(),
            parent_git_scope=None,
            parent_sandbox_conn=None,
            llm=AsyncMock(),
            config=LoopConfig(),
        )

        assert len(results) == 2
        success_results = [r for r in results if r["status"] == "success"]
        error_results = [r for r in results if r["status"] == "error"]
        assert len(success_results) == 1
        assert len(error_results) == 1
        assert success_results[0]["agent"] == "builder"
        assert error_results[0]["agent"] == "unknown"


class TestSandboxResolution:
    @pytest.mark.asyncio
    async def test_sandbox_sharing_same_git(self):
        child = _make_agent("builder", "Builds", sandbox_git="current_project")
        parent = _make_agent("dev", "Dev", subagents=["builder"], sandbox_git="current_project")
        parent_conn = MCPConnection(server_name="sandbox", endpoint="http://localhost:9001")

        mcp = SubagentsMCP(
            agent_loader=_make_agent_loader({"builder": child}),
            loop_runner=_make_loop_runner(),
        )

        results = await mcp.execute(
            agents=[{"agent": "builder", "prompt": "build"}],
            parent_agent=parent,
            parent_tool_provider=MagicMock(),
            parent_git_scope="current_project",
            parent_sandbox_conn=parent_conn,
            llm=AsyncMock(),
            config=LoopConfig(),
        )

        assert results[0]["status"] == "success"

    @pytest.mark.asyncio
    async def test_sandbox_new_different_git(self):
        child = _make_agent("builder", "Builds", sandbox_git="update_core")
        parent = _make_agent("dev", "Dev", subagents=["builder"], sandbox_git="current_project")
        parent_conn = MCPConnection(server_name="sandbox", endpoint="http://localhost:9001")
        new_conn = MCPConnection(server_name="sandbox", endpoint="http://localhost:9002")
        resolver = AsyncMock(return_value=new_conn)

        mcp = SubagentsMCP(
            agent_loader=_make_agent_loader({"builder": child}),
            sandbox_resolver=resolver,
            loop_runner=_make_loop_runner(),
        )

        results = await mcp.execute(
            agents=[{"agent": "builder", "prompt": "build"}],
            parent_agent=parent,
            parent_tool_provider=MagicMock(),
            parent_git_scope="current_project",
            parent_sandbox_conn=parent_conn,
            llm=AsyncMock(),
            config=LoopConfig(),
        )

        assert results[0]["status"] == "success"
        resolver.assert_called_once_with("update_core")

    @pytest.mark.asyncio
    async def test_sandbox_no_sandbox(self):
        child = _make_agent("planner", "Plans", sandbox_git=None)
        parent = _make_agent("dev", "Dev", subagents=["planner"])
        resolver = AsyncMock()

        mcp = SubagentsMCP(
            agent_loader=_make_agent_loader({"planner": child}),
            sandbox_resolver=resolver,
            loop_runner=_make_loop_runner(),
        )

        results = await mcp.execute(
            agents=[{"agent": "planner", "prompt": "plan"}],
            parent_agent=parent,
            parent_tool_provider=MagicMock(),
            parent_git_scope="current_project",
            parent_sandbox_conn=MCPConnection(server_name="sandbox", endpoint=None),
            llm=AsyncMock(),
            config=LoopConfig(),
        )

        assert results[0]["status"] == "success"
        resolver.assert_not_called()

    @pytest.mark.asyncio
    async def test_sandbox_no_resolver_different_git(self):
        child = _make_agent("builder", "Builds", sandbox_git="update_core")
        parent = _make_agent("dev", "Dev", subagents=["builder"], sandbox_git="current_project")

        mcp = SubagentsMCP(
            agent_loader=_make_agent_loader({"builder": child}),
            sandbox_resolver=None,
            loop_runner=_make_loop_runner(),
        )

        results = await mcp.execute(
            agents=[{"agent": "builder", "prompt": "build"}],
            parent_agent=parent,
            parent_tool_provider=MagicMock(),
            parent_git_scope="current_project",
            parent_sandbox_conn=MCPConnection(server_name="sandbox", endpoint=None),
            llm=AsyncMock(),
            config=LoopConfig(),
        )

        assert results[0]["status"] == "success"

    @pytest.mark.asyncio
    async def test_sandbox_parent_no_sandbox_child_needs_sandbox(self):
        child = _make_agent("builder", "Builds", sandbox_git="current_project")
        parent = _make_agent("planner", "Plans", subagents=["builder"])
        new_conn = MCPConnection(server_name="sandbox", endpoint="http://localhost:9001")
        resolver = AsyncMock(return_value=new_conn)

        mcp = SubagentsMCP(
            agent_loader=_make_agent_loader({"builder": child}),
            sandbox_resolver=resolver,
            loop_runner=_make_loop_runner(),
        )

        results = await mcp.execute(
            agents=[{"agent": "builder", "prompt": "build"}],
            parent_agent=parent,
            parent_tool_provider=MagicMock(),
            parent_git_scope=None,
            parent_sandbox_conn=None,
            llm=AsyncMock(),
            config=LoopConfig(),
        )

        assert results[0]["status"] == "success"
        resolver.assert_called_once_with("current_project")


class TestResolveSandboxDirect:
    @pytest.mark.asyncio
    async def test_child_no_sandbox(self):
        mcp = SubagentsMCP(agent_loader=lambda x: None)
        result = await mcp._resolve_sandbox(None, "current_project", None)
        assert result is None

    @pytest.mark.asyncio
    async def test_share_same_git_scope(self):
        parent_conn = MCPConnection(server_name="sandbox", endpoint="http://localhost:9001")
        mcp = SubagentsMCP(agent_loader=lambda x: None)
        result = await mcp._resolve_sandbox("current_project", "current_project", parent_conn)
        assert result is parent_conn

    @pytest.mark.asyncio
    async def test_different_git_calls_resolver(self):
        new_conn = MCPConnection(server_name="sandbox", endpoint="http://localhost:9002")
        resolver = AsyncMock(return_value=new_conn)
        mcp = SubagentsMCP(agent_loader=lambda x: None, sandbox_resolver=resolver)

        result = await mcp._resolve_sandbox(
            "update_core",
            "current_project",
            MCPConnection(server_name="sandbox", endpoint="http://localhost:9001"),
        )
        assert result is new_conn
        resolver.assert_called_once_with("update_core")

    @pytest.mark.asyncio
    async def test_different_git_no_resolver(self):
        mcp = SubagentsMCP(agent_loader=lambda x: None, sandbox_resolver=None)
        result = await mcp._resolve_sandbox(
            "update_core",
            "current_project",
            MCPConnection(server_name="sandbox", endpoint="http://localhost:9001"),
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_same_git_no_parent_conn(self):
        resolver = AsyncMock(return_value=MCPConnection(server_name="sandbox", endpoint=None))
        mcp = SubagentsMCP(agent_loader=lambda x: None, sandbox_resolver=resolver)
        await mcp._resolve_sandbox("current_project", "current_project", None)
        resolver.assert_called_once_with("current_project")

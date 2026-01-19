"""Architect executor for architecture and design actions."""

import json
import structlog
from typing import Any

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.language_models import BaseChatModel

from .base import Executor, ExecutorResult
from druppie.core.models import Step, TokenUsage

logger = structlog.get_logger()


ARCHITECT_SYSTEM_PROMPT = """You are a software architect AI assistant.
Your role is to create technical designs, architecture documents, and system specifications.

Always respond with structured, professional technical content.
When creating diagrams, use Mermaid syntax.
When documenting decisions, use the ADR (Architecture Decision Record) format.

Be specific, practical, and consider real-world constraints."""


class ArchitectExecutor(Executor):
    """Executes architect actions for design and documentation.

    Handles actions:
    - design_architecture: Create architecture design
    - create_documentation: Create technical documentation
    - design_api: Design API specifications
    - create_diagram: Create architecture diagrams
    - record_decision: Create architecture decision records
    """

    HANDLED_ACTIONS = {
        "design_architecture",
        "architectural_design",
        "create_documentation",
        "documentation_assembly",
        "design_api",
        "create_diagram",
        "record_decision",
        "decision_recording",
        "review_architecture",
    }

    def __init__(self, llm: BaseChatModel | None = None):
        """Initialize the ArchitectExecutor.

        Args:
            llm: LangChain chat model for generating content
        """
        self.llm = llm
        self.logger = logger.bind(executor="architect")

    def set_llm(self, llm: BaseChatModel) -> None:
        """Set the LLM for content generation."""
        self.llm = llm

    def can_handle(self, action: str) -> bool:
        """Check if this executor handles the action."""
        return action in self.HANDLED_ACTIONS

    async def execute(
        self,
        step: Step,
        context: dict[str, Any] | None = None,
    ) -> ExecutorResult:
        """Execute an architect action."""
        context = context or {}
        action = step.action

        if self.llm is None:
            return ExecutorResult(
                success=False,
                error="No LLM configured for architect executor",
            )

        try:
            if action in ("design_architecture", "architectural_design"):
                return await self._design_architecture(step, context)
            elif action in ("create_documentation", "documentation_assembly"):
                return await self._create_documentation(step, context)
            elif action == "design_api":
                return await self._design_api(step, context)
            elif action == "create_diagram":
                return await self._create_diagram(step, context)
            elif action in ("record_decision", "decision_recording"):
                return await self._record_decision(step, context)
            elif action == "review_architecture":
                return await self._review_architecture(step, context)
            else:
                return ExecutorResult(
                    success=False,
                    error=f"Unknown action: {action}",
                )
        except Exception as e:
            self.logger.error("architect_action_failed", action=action, error=str(e))
            return ExecutorResult(success=False, error=str(e))

    async def _design_architecture(
        self,
        step: Step,
        context: dict[str, Any],
    ) -> ExecutorResult:
        """Create an architecture design."""
        params = step.params
        requirements = params.get("requirements", [])
        constraints = params.get("constraints", [])
        existing_systems = params.get("existing_systems", [])

        prompt = f"""Create a software architecture design based on the following:

Requirements:
{json.dumps(requirements, indent=2)}

Constraints:
{json.dumps(constraints, indent=2)}

Existing systems to integrate with:
{json.dumps(existing_systems, indent=2)}

Please provide:
1. Architecture overview
2. Component diagram (in Mermaid syntax)
3. Key design decisions
4. Integration points
5. Technology stack recommendations"""

        messages = [
            SystemMessage(content=ARCHITECT_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]

        response = await self.llm.ainvoke(messages)

        usage = self._extract_usage(response)

        return ExecutorResult(
            success=True,
            result={
                "architecture_design": response.content,
                "type": "architecture",
            },
            usage=usage,
            output_messages=["Architecture design created"],
        )

    async def _create_documentation(
        self,
        step: Step,
        context: dict[str, Any],
    ) -> ExecutorResult:
        """Create technical documentation."""
        params = step.params
        doc_type = params.get("type", "technical")
        topic = params.get("topic", "System Documentation")
        sections = params.get("sections", [])
        source_content = params.get("content", "")

        prompt = f"""Create {doc_type} documentation for: {topic}

{"Requested sections: " + json.dumps(sections) if sections else ""}

{"Source content to document:" + source_content if source_content else ""}

Create comprehensive, well-structured documentation with:
1. Clear headings and sections
2. Code examples where relevant
3. Diagrams in Mermaid syntax
4. Best practices and recommendations"""

        messages = [
            SystemMessage(content=ARCHITECT_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]

        response = await self.llm.ainvoke(messages)

        usage = self._extract_usage(response)

        return ExecutorResult(
            success=True,
            result={
                "documentation": response.content,
                "type": doc_type,
                "topic": topic,
            },
            usage=usage,
            output_messages=[f"Documentation created for: {topic}"],
        )

    async def _design_api(
        self,
        step: Step,
        context: dict[str, Any],
    ) -> ExecutorResult:
        """Design API specifications."""
        params = step.params
        api_name = params.get("name", "API")
        endpoints = params.get("endpoints", [])
        resources = params.get("resources", [])

        prompt = f"""Design an API specification for: {api_name}

{"Endpoints: " + json.dumps(endpoints) if endpoints else ""}
{"Resources: " + json.dumps(resources) if resources else ""}

Provide:
1. OpenAPI/Swagger specification
2. Endpoint documentation
3. Request/Response examples
4. Authentication recommendations
5. Error handling patterns"""

        messages = [
            SystemMessage(content=ARCHITECT_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]

        response = await self.llm.ainvoke(messages)

        usage = self._extract_usage(response)

        return ExecutorResult(
            success=True,
            result={
                "api_design": response.content,
                "name": api_name,
            },
            usage=usage,
            output_messages=[f"API design created for: {api_name}"],
        )

    async def _create_diagram(
        self,
        step: Step,
        context: dict[str, Any],
    ) -> ExecutorResult:
        """Create architecture diagrams."""
        params = step.params
        diagram_type = params.get("type", "flowchart")
        description = params.get("description", "")
        components = params.get("components", [])

        prompt = f"""Create a {diagram_type} diagram in Mermaid syntax.

Description: {description}
{"Components: " + json.dumps(components) if components else ""}

Provide the Mermaid diagram code that can be rendered."""

        messages = [
            SystemMessage(content=ARCHITECT_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]

        response = await self.llm.ainvoke(messages)

        usage = self._extract_usage(response)

        return ExecutorResult(
            success=True,
            result={
                "diagram": response.content,
                "type": diagram_type,
            },
            usage=usage,
            output_messages=[f"Diagram created: {diagram_type}"],
        )

    async def _record_decision(
        self,
        step: Step,
        context: dict[str, Any],
    ) -> ExecutorResult:
        """Record an architecture decision (ADR)."""
        params = step.params
        title = params.get("title", "Architecture Decision")
        decision = params.get("decision", "")
        context_info = params.get("context", "")
        alternatives = params.get("alternatives", [])

        prompt = f"""Create an Architecture Decision Record (ADR) for:

Title: {title}
Decision: {decision}
Context: {context_info}
{"Alternatives considered: " + json.dumps(alternatives) if alternatives else ""}

Format the ADR with standard sections:
1. Title
2. Status (Proposed/Accepted/Deprecated/Superseded)
3. Context
4. Decision
5. Consequences
6. Alternatives Considered"""

        messages = [
            SystemMessage(content=ARCHITECT_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]

        response = await self.llm.ainvoke(messages)

        usage = self._extract_usage(response)

        return ExecutorResult(
            success=True,
            result={
                "adr": response.content,
                "title": title,
            },
            usage=usage,
            output_messages=[f"ADR created: {title}"],
        )

    async def _review_architecture(
        self,
        step: Step,
        context: dict[str, Any],
    ) -> ExecutorResult:
        """Review existing architecture."""
        params = step.params
        architecture_doc = params.get("document", "")
        focus_areas = params.get("focus_areas", [])

        prompt = f"""Review the following architecture:

{architecture_doc}

{"Focus areas: " + json.dumps(focus_areas) if focus_areas else ""}

Provide:
1. Strengths of the architecture
2. Potential issues or risks
3. Recommendations for improvement
4. Security considerations
5. Scalability assessment"""

        messages = [
            SystemMessage(content=ARCHITECT_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]

        response = await self.llm.ainvoke(messages)

        usage = self._extract_usage(response)

        return ExecutorResult(
            success=True,
            result={
                "review": response.content,
                "type": "architecture_review",
            },
            usage=usage,
            output_messages=["Architecture review completed"],
        )

    def _extract_usage(self, response) -> TokenUsage:
        """Extract token usage from LLM response."""
        usage = TokenUsage()
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            usage.prompt_tokens = response.usage_metadata.get("input_tokens", 0)
            usage.completion_tokens = response.usage_metadata.get("output_tokens", 0)
            usage.total_tokens = usage.prompt_tokens + usage.completion_tokens
        return usage

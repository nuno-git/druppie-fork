"""Business Analyst executor for requirements and analysis actions."""

import json
import structlog
from typing import Any

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.language_models import BaseChatModel

from .base import Executor, ExecutorResult
from druppie.core.models import Step, TokenUsage

logger = structlog.get_logger()


BA_SYSTEM_PROMPT = """You are a Business Analyst AI assistant.
Your role is to analyze business requirements, create user stories, and ensure clarity between business needs and technical solutions.

Always:
- Use clear, structured formats (user stories, acceptance criteria)
- Ask clarifying questions when requirements are ambiguous
- Consider stakeholder perspectives
- Map business value to technical features
- Use standard BA templates and formats"""


class BusinessAnalystExecutor(Executor):
    """Executes business analyst actions for requirements analysis.

    Handles actions:
    - analyze_requirements: Analyze and structure requirements
    - create_user_stories: Create user stories from requirements
    - create_epics: Define epics for large features
    - stakeholder_analysis: Analyze stakeholders
    - create_acceptance_criteria: Define acceptance criteria
    - validate_requirements: Validate requirements for completeness
    """

    HANDLED_ACTIONS = {
        "analyze_requirements",
        "problem_exploration",
        "create_user_stories",
        "user_story_refinement",
        "create_epics",
        "epic_definition",
        "stakeholder_analysis",
        "stakeholder_understanding",
        "create_acceptance_criteria",
        "validate_requirements",
        "requirement_structuring",
        "validation",
        "review",
    }

    def __init__(self, llm: BaseChatModel | None = None):
        """Initialize the BusinessAnalystExecutor.

        Args:
            llm: LangChain chat model for generating content
        """
        self.llm = llm
        self.logger = logger.bind(executor="business_analyst")

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
        """Execute a business analyst action."""
        context = context or {}
        action = step.action

        if self.llm is None:
            return ExecutorResult(
                success=False,
                error="No LLM configured for business analyst executor",
            )

        try:
            if action in ("analyze_requirements", "problem_exploration", "requirement_structuring"):
                return await self._analyze_requirements(step, context)
            elif action in ("create_user_stories", "user_story_refinement"):
                return await self._create_user_stories(step, context)
            elif action in ("create_epics", "epic_definition"):
                return await self._create_epics(step, context)
            elif action in ("stakeholder_analysis", "stakeholder_understanding"):
                return await self._stakeholder_analysis(step, context)
            elif action == "create_acceptance_criteria":
                return await self._create_acceptance_criteria(step, context)
            elif action in ("validate_requirements", "validation", "review"):
                return await self._validate_requirements(step, context)
            else:
                return ExecutorResult(
                    success=False,
                    error=f"Unknown action: {action}",
                )
        except Exception as e:
            self.logger.error("ba_action_failed", action=action, error=str(e))
            return ExecutorResult(success=False, error=str(e))

    async def _analyze_requirements(
        self,
        step: Step,
        context: dict[str, Any],
    ) -> ExecutorResult:
        """Analyze and structure requirements."""
        params = step.params
        raw_requirements = params.get("requirements", "")
        domain = params.get("domain", "")
        stakeholders = params.get("stakeholders", [])

        prompt = f"""Analyze and structure the following requirements:

Raw Requirements:
{raw_requirements}

{"Domain: " + domain if domain else ""}
{"Stakeholders: " + json.dumps(stakeholders) if stakeholders else ""}

Provide:
1. Categorized functional requirements
2. Non-functional requirements
3. Constraints and assumptions
4. Out of scope items
5. Questions for clarification
6. Risk areas"""

        messages = [
            SystemMessage(content=BA_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]

        response = await self.llm.ainvoke(messages)

        usage = self._extract_usage(response)

        return ExecutorResult(
            success=True,
            result={
                "requirements_analysis": response.content,
                "type": "requirements",
            },
            usage=usage,
            output_messages=["Requirements analyzed"],
        )

    async def _create_user_stories(
        self,
        step: Step,
        context: dict[str, Any],
    ) -> ExecutorResult:
        """Create user stories from requirements."""
        params = step.params
        requirements = params.get("requirements", "")
        personas = params.get("personas", [])
        epic = params.get("epic", "")

        prompt = f"""Create user stories based on:

Requirements:
{requirements}

{"Epic: " + epic if epic else ""}
{"Personas: " + json.dumps(personas) if personas else ""}

For each user story, provide:
1. Title
2. User story format: "As a [persona], I want [goal] so that [benefit]"
3. Acceptance criteria (Given/When/Then format)
4. Story points estimate (1, 2, 3, 5, 8, 13)
5. Dependencies"""

        messages = [
            SystemMessage(content=BA_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]

        response = await self.llm.ainvoke(messages)

        usage = self._extract_usage(response)

        return ExecutorResult(
            success=True,
            result={
                "user_stories": response.content,
                "type": "user_stories",
            },
            usage=usage,
            output_messages=["User stories created"],
        )

    async def _create_epics(
        self,
        step: Step,
        context: dict[str, Any],
    ) -> ExecutorResult:
        """Create epics for large features."""
        params = step.params
        feature_description = params.get("feature", "")
        business_value = params.get("business_value", "")
        scope = params.get("scope", "")

        prompt = f"""Create an epic definition for:

Feature: {feature_description}
{"Business Value: " + business_value if business_value else ""}
{"Scope: " + scope if scope else ""}

Provide:
1. Epic title and description
2. Business value statement
3. High-level user stories (features breakdown)
4. Success metrics
5. Assumptions and risks
6. Dependencies
7. Estimated effort (T-shirt sizing: S, M, L, XL)"""

        messages = [
            SystemMessage(content=BA_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]

        response = await self.llm.ainvoke(messages)

        usage = self._extract_usage(response)

        return ExecutorResult(
            success=True,
            result={
                "epic": response.content,
                "type": "epic",
            },
            usage=usage,
            output_messages=["Epic created"],
        )

    async def _stakeholder_analysis(
        self,
        step: Step,
        context: dict[str, Any],
    ) -> ExecutorResult:
        """Analyze stakeholders."""
        params = step.params
        project_context = params.get("context", "")
        known_stakeholders = params.get("stakeholders", [])

        prompt = f"""Perform stakeholder analysis for:

Project Context:
{project_context}

{"Known stakeholders: " + json.dumps(known_stakeholders) if known_stakeholders else ""}

Provide:
1. Stakeholder identification
2. Stakeholder matrix (power/interest grid)
3. Communication strategy per stakeholder
4. Potential concerns and mitigation
5. RACI matrix recommendations"""

        messages = [
            SystemMessage(content=BA_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]

        response = await self.llm.ainvoke(messages)

        usage = self._extract_usage(response)

        return ExecutorResult(
            success=True,
            result={
                "stakeholder_analysis": response.content,
                "type": "stakeholder_analysis",
            },
            usage=usage,
            output_messages=["Stakeholder analysis completed"],
        )

    async def _create_acceptance_criteria(
        self,
        step: Step,
        context: dict[str, Any],
    ) -> ExecutorResult:
        """Create acceptance criteria for requirements."""
        params = step.params
        requirement = params.get("requirement", "")
        user_story = params.get("user_story", "")

        prompt = f"""Create detailed acceptance criteria for:

{"Requirement: " + requirement if requirement else ""}
{"User Story: " + user_story if user_story else ""}

Provide acceptance criteria in Given/When/Then (Gherkin) format:
- Cover happy path scenarios
- Cover edge cases
- Cover error scenarios
- Include data validation criteria"""

        messages = [
            SystemMessage(content=BA_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]

        response = await self.llm.ainvoke(messages)

        usage = self._extract_usage(response)

        return ExecutorResult(
            success=True,
            result={
                "acceptance_criteria": response.content,
                "type": "acceptance_criteria",
            },
            usage=usage,
            output_messages=["Acceptance criteria created"],
        )

    async def _validate_requirements(
        self,
        step: Step,
        context: dict[str, Any],
    ) -> ExecutorResult:
        """Validate requirements for completeness."""
        params = step.params
        requirements = params.get("requirements", "")
        validation_criteria = params.get("criteria", [])

        prompt = f"""Validate the following requirements:

Requirements:
{requirements}

{"Validation criteria: " + json.dumps(validation_criteria) if validation_criteria else ""}

Check for:
1. Completeness - Are all aspects covered?
2. Consistency - Are there contradictions?
3. Clarity - Are requirements unambiguous?
4. Testability - Can each requirement be verified?
5. Traceability - Can requirements be tracked?
6. Feasibility - Are requirements achievable?

Provide a validation report with:
- Overall assessment
- Issues found
- Recommendations
- Questions for stakeholders"""

        messages = [
            SystemMessage(content=BA_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]

        response = await self.llm.ainvoke(messages)

        usage = self._extract_usage(response)

        return ExecutorResult(
            success=True,
            result={
                "validation_report": response.content,
                "type": "validation",
            },
            usage=usage,
            output_messages=["Requirements validated"],
        )

    def _extract_usage(self, response) -> TokenUsage:
        """Extract token usage from LLM response."""
        usage = TokenUsage()
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            usage.prompt_tokens = response.usage_metadata.get("input_tokens", 0)
            usage.completion_tokens = response.usage_metadata.get("output_tokens", 0)
            usage.total_tokens = usage.prompt_tokens + usage.completion_tokens
        return usage

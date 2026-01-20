"""Router for analyzing user intent.

The Router is the first component that processes user input.
It classifies intent as one of 3 actions and extracts project context.
"""

import json
import re

import structlog
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from druppie.core.models import Intent, IntentAction, TokenUsage

logger = structlog.get_logger()


ROUTER_SYSTEM_PROMPT = """You are an intent analysis system for Druppie, a governance AI platform.

Analyze the user's request and classify it into ONE of these three actions:

1. create_project: User wants to BUILD something NEW
   - Create a new application, website, service, tool
   - Build a new feature from scratch
   - Start a new project

2. update_project: User wants to MODIFY something EXISTING
   - Fix a bug in existing code
   - Update or improve existing features
   - Refactor existing code
   - Add to an existing project

3. general_chat: User is asking a question or having a conversation
   - Asking how something works
   - Requesting explanations
   - General questions not requiring code changes

If the request is unclear and you need more information to proceed, set clarification_needed to true.

Extract relevant project context like:
- repo_url: Git repository URL if mentioned
- project_name: Name of the project if mentioned
- task_description: Clear description of what needs to be done
- technologies: Any mentioned technologies, languages, frameworks

For general_chat, provide a helpful direct answer.

Respond ONLY with valid JSON:
{
    "action": "create_project|update_project|general_chat",
    "language": "en",
    "prompt": "Summarized intent in user's language",
    "clarification_needed": false,
    "clarification_question": null,
    "answer": "Direct answer if general_chat, otherwise null",
    "project_context": {
        "repo_url": "optional git url",
        "project_name": "optional name",
        "task_description": "what needs to be done",
        "technologies": ["optional", "list"]
    }
}"""


class Router:
    """Analyzes user intent and routes to appropriate handlers.

    The Router uses an LLM to understand what the user wants and
    produces a structured Intent with one of 3 actions:
    - CREATE_PROJECT: Build something new
    - UPDATE_PROJECT: Modify existing project
    - GENERAL_CHAT: Answer questions
    """

    def __init__(self, llm: BaseChatModel, debug: bool = False):
        """Initialize the Router.

        Args:
            llm: LangChain chat model for intent analysis
            debug: Enable debug logging
        """
        self.llm = llm
        self.debug = debug
        self.logger = logger.bind(component="router")

    async def analyze(
        self, user_input: str, plan_id: str | None = None
    ) -> tuple[Intent, TokenUsage]:
        """Analyze user input and determine intent.

        Args:
            user_input: The user's message
            plan_id: Optional plan ID for context

        Returns:
            Tuple of (Intent, TokenUsage)
        """
        self.logger.info(
            "analyzing_intent", input_length=len(user_input), plan_id=plan_id
        )

        messages = [
            SystemMessage(content=ROUTER_SYSTEM_PROMPT),
            HumanMessage(content=user_input),
        ]

        try:
            response = await self.llm.ainvoke(messages)
            content = response.content

            # Parse the JSON response
            data = self._parse_json_response(content, user_input)

            # Map action string to enum
            action_map = {
                "create_project": IntentAction.CREATE_PROJECT,
                "update_project": IntentAction.UPDATE_PROJECT,
                "general_chat": IntentAction.GENERAL_CHAT,
            }

            intent = Intent(
                initial_prompt=user_input,
                prompt=data.get("prompt", user_input),
                action=action_map.get(
                    data.get("action", "general_chat"), IntentAction.GENERAL_CHAT
                ),
                language=data.get("language", "en"),
                answer=data.get("answer"),
                clarification_needed=data.get("clarification_needed", False),
                clarification_question=data.get("clarification_question"),
                project_context=data.get("project_context") or {},
            )

            # Calculate token usage
            usage = TokenUsage()
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                usage.prompt_tokens = response.usage_metadata.get("input_tokens", 0)
                usage.completion_tokens = response.usage_metadata.get("output_tokens", 0)
                usage.total_tokens = usage.prompt_tokens + usage.completion_tokens

            self.logger.info(
                "intent_analyzed",
                action=intent.action.value,
                language=intent.language,
                clarification_needed=intent.clarification_needed,
            )

            return intent, usage

        except Exception as e:
            self.logger.error("intent_analysis_failed", error=str(e))
            # Return a default general_chat intent on error
            return (
                Intent(
                    initial_prompt=user_input,
                    prompt=user_input,
                    action=IntentAction.GENERAL_CHAT,
                    answer=f"I encountered an error analyzing your request: {e}",
                    project_context={},
                ),
                TokenUsage(),
            )

    def _parse_json_response(self, content: str, user_input: str) -> dict:
        """Parse JSON from LLM response, with fallback."""
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # Try to extract JSON from response
            json_match = re.search(r"\{[\s\S]*\}", content)
            if json_match:
                return json.loads(json_match.group())
            else:
                # Default to general chat
                return {
                    "action": "general_chat",
                    "language": "en",
                    "prompt": user_input,
                    "answer": content,
                    "project_context": {},
                }

    def is_direct_response(self, intent: Intent) -> bool:
        """Check if the intent should be handled with a direct response.

        Returns True for general_chat actions that don't need planning.
        """
        return intent.action == IntentAction.GENERAL_CHAT and intent.answer is not None

    def needs_clarification(self, intent: Intent) -> bool:
        """Check if the intent needs clarification from the user."""
        return intent.clarification_needed and intent.clarification_question is not None

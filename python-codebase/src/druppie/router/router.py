"""Router for analyzing user intent.

The Router is the first component that processes user input.
It determines what the user wants and routes to the appropriate handler.
"""

import json
import structlog

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.language_models import BaseChatModel

from druppie.core.models import Intent, IntentAction, TokenUsage

logger = structlog.get_logger()


ROUTER_SYSTEM_PROMPT = """You are an intent analysis system for Druppie, a governance AI platform.

Analyze the user's request and classify it into one of these actions:
- create_project: User wants to create something new (code, document, design, etc.)
- update_project: User wants to modify or update an existing project
- query_registry: User wants to search or query available capabilities
- orchestrate_complex: User wants to coordinate multiple agents for a complex task
- general_chat: User is asking a general question or having a conversation

Also determine:
- category: infrastructure, service, search, create_content, or unknown
- content_type: code, document, video, image, audio, or null
- language: detected language code (en, nl, de, fr, etc.)

If the action is "general_chat", provide a helpful direct answer.

Respond ONLY with valid JSON in this exact format:
{
    "action": "create_project|update_project|query_registry|orchestrate_complex|general_chat",
    "category": "infrastructure|service|search|create_content|unknown",
    "content_type": "code|document|video|image|audio|null",
    "language": "en",
    "prompt": "Summarized intent in user's language",
    "answer": "Direct answer if general_chat, otherwise null",
    "entities": {
        "project_name": "optional",
        "technologies": ["optional", "list"],
        "requirements": ["optional", "list"]
    }
}"""


class Router:
    """Analyzes user intent and routes to appropriate handlers.

    The Router uses an LLM to understand what the user wants and
    produces a structured Intent that the Planner can use.
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

    async def analyze(self, user_input: str, plan_id: str | None = None) -> tuple[Intent, TokenUsage]:
        """Analyze user input and determine intent.

        Args:
            user_input: The user's message
            plan_id: Optional plan ID for context

        Returns:
            Tuple of (Intent, TokenUsage)
        """
        self.logger.info("analyzing_intent", input_length=len(user_input), plan_id=plan_id)

        messages = [
            SystemMessage(content=ROUTER_SYSTEM_PROMPT),
            HumanMessage(content=user_input),
        ]

        try:
            response = await self.llm.ainvoke(messages)
            content = response.content

            # Parse the JSON response
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                # Try to extract JSON from response
                import re
                json_match = re.search(r'\{[\s\S]*\}', content)
                if json_match:
                    data = json.loads(json_match.group())
                else:
                    # Default to general chat
                    data = {
                        "action": "general_chat",
                        "category": "unknown",
                        "content_type": None,
                        "language": "en",
                        "prompt": user_input,
                        "answer": content,
                        "entities": {},
                    }

            # Map action string to enum
            action_map = {
                "create_project": IntentAction.CREATE_PROJECT,
                "update_project": IntentAction.UPDATE_PROJECT,
                "query_registry": IntentAction.QUERY_REGISTRY,
                "orchestrate_complex": IntentAction.ORCHESTRATE_COMPLEX,
                "general_chat": IntentAction.GENERAL_CHAT,
            }

            intent = Intent(
                initial_prompt=user_input,
                prompt=data.get("prompt", user_input),
                action=action_map.get(data.get("action", "general_chat"), IntentAction.GENERAL_CHAT),
                category=data.get("category", "unknown"),
                content_type=data.get("content_type"),
                language=data.get("language", "en"),
                answer=data.get("answer"),
                entities=data.get("entities", {}),
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
                category=intent.category,
                language=intent.language,
            )

            return intent, usage

        except Exception as e:
            self.logger.error("intent_analysis_failed", error=str(e))
            # Return a default general_chat intent on error
            return Intent(
                initial_prompt=user_input,
                prompt=user_input,
                action=IntentAction.GENERAL_CHAT,
                answer=f"I encountered an error analyzing your request: {e}",
            ), TokenUsage()

    def is_direct_response(self, intent: Intent) -> bool:
        """Check if the intent should be handled with a direct response.

        Returns True for general_chat actions that don't need planning.
        """
        return intent.action == IntentAction.GENERAL_CHAT and intent.answer is not None

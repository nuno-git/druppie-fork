"""Prompt builder - constructs system and user prompts for agents."""

from druppie.agents.definition_loader import AgentDefinitionLoader
from druppie.domain.agent_definition import AgentDefinition


class PromptBuilder:
    """Builds system and user prompts for an agent.

    Initialized with agent identity and definition;
    all methods are pure (no side effects beyond reading the common prompt cache).
    """

    def __init__(self, agent_id: str, definition: AgentDefinition):
        self.agent_id = agent_id
        self.definition = definition

    def build_system_prompt(self) -> str:
        """Build the full system prompt.

        Appends declared system prompts from system_prompts/*.yaml.
        Skills are NOT listed here — they're expressed via the invoke_skill
        tool definition (enum + descriptions) in AgentLoop._prepare_tools().
        """
        base_prompt = self.definition.system_prompt

        # Append system prompts declared in agent definition
        for prompt_id in self.definition.system_prompts:
            prompt = AgentDefinitionLoader.load_system_prompt(prompt_id)
            base_prompt += "\n\n" + prompt

        return base_prompt

    def build_user_prompt(self, prompt: str, context: dict = None) -> str:
        """Build the user prompt with optional context and clarifications."""
        if not context:
            return prompt

        # Extract clarifications for natural inclusion
        clarifications = context.get("clarifications", [])

        # Build context string WITHOUT clarifications
        context_items = {k: v for k, v in context.items() if k != "clarifications"}
        context_str = "\n".join(
            f"- {key}: {value}" for key, value in context_items.items()
        )

        # Build user response section if present
        user_response_str = ""
        if clarifications:
            latest = clarifications[-1]
            question = latest.get("question", "")
            answer = latest.get("answer", "")
            user_response_str = f"""

USER RESPONSE:
You previously asked: {question[:200]}{'...' if len(question) > 200 else ''}
User's answer: {answer}
"""

        return f"""CONTEXT:
{context_str}

TASK:
{prompt}{user_response_str}"""

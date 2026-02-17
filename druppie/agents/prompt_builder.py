"""Prompt builder - constructs system and user prompts for agents."""

from druppie.agents.definition_loader import AgentDefinitionLoader
from druppie.domain.agent_definition import AgentDefinition

# Language code to human-readable name mapping
LANGUAGE_NAMES = {"nl": "DUTCH", "en": "ENGLISH"}
DEFAULT_LANGUAGE = "nl"


class PromptBuilder:
    """Builds system and user prompts for an agent.

    Initialized with agent identity and definition;
    all methods are pure (no side effects beyond reading the common prompt cache).
    """

    def __init__(self, agent_id: str, definition: AgentDefinition):
        self.agent_id = agent_id
        self.definition = definition

    def build_system_prompt(self, language: str = DEFAULT_LANGUAGE, language_info: dict = None) -> str:
        """Build the full system prompt with language block at the TOP.

        Language goes first so the model sees it before all other instructions.
        This is critical for weaker models (glm-4) where a buried instruction
        gets drowned out by hundreds of lines of English-language content.
        """
        base_prompt = self.definition.system_prompt

        # Inject common instructions (shared across agents)
        common_prompt = AgentDefinitionLoader.load_common_prompt()
        if common_prompt and "[COMMON_INSTRUCTIONS]" in base_prompt:
            base_prompt = base_prompt.replace("[COMMON_INSTRUCTIONS]", common_prompt)

        # Language block FIRST — model sees it before all agent instructions
        return self._build_language_block(language, language_info) + base_prompt

    def build_user_prompt(self, prompt: str, context: dict = None) -> str:
        """Build the user prompt with optional context and clarifications."""
        if not context:
            return prompt

        # Extract clarifications for natural inclusion
        clarifications = context.get("clarifications", [])

        # Build context string WITHOUT clarifications, conversational_language, and language_info
        context_items = {
            k: v for k, v in context.items()
            if k not in ("clarifications", "conversational_language", "language_info")
        }
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

    # ------------------------------------------------------------------
    # Language block — the ONE place language is specified
    # ------------------------------------------------------------------

    @staticmethod
    def _build_language_block(language: str, language_info: dict = None) -> str:
        """Build the leading language instruction block.

        Placed at the TOP of the system prompt. Made assertive so the model
        follows it even when other languages appear in the task prompt,
        conversation history, or tool results.
        """
        lang_name = LANGUAGE_NAMES.get(language, language.upper())

        if language_info and language_info.get("detection_status") == "detected":
            preview = language_info.get("detected_from", "")
            detected = language_info.get("detected_language", language)
            detected_name = LANGUAGE_NAMES.get(detected, detected.upper())
            detection_line = f"Auto-detected from user input: \"{preview}\" → {detected} ({detected_name})"
        elif language_info and language_info.get("detection_status") == "failed":
            preview = language_info.get("detected_from", "")
            detection_line = f"User input \"{preview}\" too short to detect. Using default: {language} ({lang_name})"
        else:
            detection_line = f"Language: {language} ({lang_name})"

        return f"""===================================================================
LEADING LANGUAGE INSTRUCTION — THIS OVERRIDES ALL OTHER LANGUAGES
===================================================================
{detection_line}

You MUST respond in {lang_name}.
Other languages may appear in the task description, conversation
history, or tool results — ignore those for your output language.
All your responses, questions, and tool arguments must be in {lang_name}.
===================================================================

"""

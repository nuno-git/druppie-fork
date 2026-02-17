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
        """Build the full system prompt with a single language block.

        Injects common instructions from _common.md (if placeholder present).
        Appends one clear language instruction block at the end.
        """
        base_prompt = self.definition.system_prompt

        # Inject common instructions (shared across agents)
        common_prompt = AgentDefinitionLoader.load_common_prompt()
        if common_prompt and "[COMMON_INSTRUCTIONS]" in base_prompt:
            base_prompt = base_prompt.replace("[COMMON_INSTRUCTIONS]", common_prompt)

        # Append the single language block
        base_prompt += self._build_language_block(language, language_info)

        return base_prompt

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
        """Build the single language instruction block.

        Three cases:
        1. language_info with detection_status="detected" → shows auto-detected info
        2. language_info with detection_status="failed" → shows default with reason
        3. No language_info (first run, no user input yet) → simple language line
        """
        lang_name = LANGUAGE_NAMES.get(language, language.upper())

        if language_info and language_info.get("detection_status") == "detected":
            preview = language_info.get("detected_from", "")
            detected = language_info.get("detected_language", language)
            detected_name = LANGUAGE_NAMES.get(detected, detected.upper())
            header = f"""

---
LANGUAGE INSTRUCTION (auto-detected):
  Last user input: "{preview}"
  Detected language: {detected} ({detected_name})"""

        elif language_info and language_info.get("detection_status") == "failed":
            preview = language_info.get("detected_from", "")
            header = f"""

---
LANGUAGE INSTRUCTION (default):
  Last user input: "{preview}" (too short to detect)
  Using default language: {language} ({lang_name})"""

        else:
            header = f"""

---
LANGUAGE INSTRUCTION:
  Language: {language} ({lang_name})"""

        return f"""{header}

  You MUST respond in {lang_name}. All responses, questions,
  and tool arguments must be in {lang_name}.
---
"""

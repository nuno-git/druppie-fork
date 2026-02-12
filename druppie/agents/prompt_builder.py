"""Prompt builder - constructs system and user prompts for agents."""

from druppie.agents.definition_loader import AgentDefinitionLoader
from druppie.domain.agent_definition import AgentDefinition

# Language code to human-readable name mapping
LANGUAGE_NAMES = {"nl": "DUTCH", "en": "ENGLISH"}


class PromptBuilder:
    """Builds system and user prompts for an agent.

    Initialized with agent identity and definition;
    all methods are pure (no side effects beyond reading the common prompt cache).
    """

    def __init__(self, agent_id: str, definition: AgentDefinition):
        self.agent_id = agent_id
        self.definition = definition

    def build_system_prompt(self, language: str = "nl") -> str:
        """Build the full system prompt with language instructions.

        Injects common instructions from _common.md (if placeholder present).
        Skills are NOT listed here — they're expressed via the invoke_skill
        tool definition (enum + descriptions) in AgentLoop._prepare_tools().
        """
        base_prompt = self.definition.system_prompt

        # Add prominent language instruction at the top
        base_prompt = self._build_language_header(language) + base_prompt

        # Inject common instructions (shared across agents)
        common_prompt = AgentDefinitionLoader.load_common_prompt()
        if common_prompt and "[COMMON_INSTRUCTIONS]" in base_prompt:
            base_prompt = base_prompt.replace("[COMMON_INSTRUCTIONS]", common_prompt)

        # Markdown language instruction for BA/architect agents
        markdown_instruction = self._get_markdown_language_instruction()
        if markdown_instruction:
            base_prompt += markdown_instruction

        # HITL question language instruction
        lang_name = LANGUAGE_NAMES.get(language, language.upper())
        base_prompt += f"""

## HITL QUESTIONS LANGUAGE

All questions you ask via hitl_ask_question or hitl_ask_multiple_choice_question
MUST be written in {lang_name}. This is mandatory - never translate to or use
any other language for questions, regardless of examples you may see elsewhere.
"""

        # Language footer reminder
        base_prompt += f"\n\n!!! FINAL REMINDER: RESPOND IN {language.upper()} ONLY !!!\n"

        return base_prompt

    def build_user_prompt(self, prompt: str, context: dict = None, language: str = "nl") -> str:
        """Build the user prompt with optional context, clarifications, and language reminder."""
        lang_name = LANGUAGE_NAMES.get(language, language.upper())
        language_reminder = f"[IMPORTANT: Respond in {lang_name} ({language.upper()}) only!]\n\n"

        if not context:
            return language_reminder + prompt

        # Extract clarifications for natural inclusion
        clarifications = context.get("clarifications", [])

        # Build context string WITHOUT clarifications and conversational_language
        context_items = {
            k: v for k, v in context.items()
            if k not in ("clarifications", "conversational_language")
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

        return f"""{language_reminder}CONTEXT:
{context_str}

TASK:
{prompt}{user_response_str}"""

    # ------------------------------------------------------------------
    # Language helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_language_header(language: str) -> str:
        """Build a prominent language instruction header."""
        border = "!" * 80
        return f"""

{border}
!!! LANGUAGE ALERT !!! LANGUAGE ALERT !!! LANGUAGE ALERT !!!
{border}
!!! YOU MUST ONLY RESPOND IN: {language.upper()} !!!
!!! LANGUAGE CODE: {language} !!!
{border}
!!! CRITICAL RULES !!!
!!! - EVERY question you ask MUST be in {language.upper()} !!!
!!! - EVERY response you give MUST be in {language.upper()} !!!
!!! - NO EXCEPTIONS - NO OTHER LANGUAGE ALLOWED !!!
{border}
!!! VIOLATION OF THIS RULE IS UNACCEPTABLE !!!
{border}
!!! REMINDER: LANGUAGE = {language.upper()} !!!
!!! REMINDER: LANGUAGE CODE = {language} !!!
{border}
!!! REPEAT: YOU MUST ONLY USE {language.upper()} !!!
{border}
"""

    def _get_markdown_language_instruction(self) -> str:
        """Generate instruction for markdown file language.

        Business Analyst and Architect agents must always create markdown in Dutch.
        """
        if self.agent_id in ("business_analyst", "architect"):
            return """

## MARKDOWN FILES LANGUAGE
IMPORTANT: When you create markdown files (functional_design.md, architecture.md), they MUST be in Dutch (language code: nl).

This rule applies ONLY to markdown files. Your questions and responses to the user must still follow the CONVERSATION_LANGUAGE setting above.
"""
        return ""

    @staticmethod
    def build_language_reminder(language: str) -> str:
        """Build a language reminder message for injection after tool responses.

        Used by Agent.continue_run() to reinforce language consistency
        when resuming from a paused state.
        """
        lang_name = LANGUAGE_NAMES.get(language, language.upper())
        return (
            f"[SYSTEM REMINDER: Continue responding in {lang_name} "
            f"({language.upper()}) only. Your next response, including any "
            f"questions, must be in {lang_name}.]"
        )

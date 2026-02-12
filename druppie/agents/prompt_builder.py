"""Prompt builder - constructs system and user prompts for agents."""

from druppie.agents.definition_loader import AgentDefinitionLoader
from druppie.domain.agent_definition import AgentDefinition

# Language code to human-readable name mapping
LANGUAGE_NAMES = {"nl": "DUTCH", "en": "ENGLISH"}


def generate_tool_descriptions(mcps: list[str]) -> str:
    """Generate formatted tool descriptions for the given MCP servers.

    Args:
        mcps: List of MCP server names (e.g., ["coding", "docker"])

    Returns:
        Formatted string with tool descriptions
    """
    if not mcps:
        return ""

    from druppie.core.tool_registry import get_tool_registry

    registry = get_tool_registry()
    descriptions = []

    for server in mcps:
        for tool_def in registry._tools.values():
            if tool_def.server == server:
                descriptions.append(f"- **{server}:{tool_def.name}**: {tool_def.description}")

    return "\n".join(descriptions)


class PromptBuilder:
    """Builds system and user prompts for an agent.

    Initialized with agent identity and definition;
    all methods are pure (no side effects beyond reading the common prompt cache).
    """

    def __init__(self, agent_id: str, definition: AgentDefinition):
        self.agent_id = agent_id
        self.definition = definition

    def build_system_prompt(
        self,
        language: str = "nl",
        supports_native_tools: bool = True,
    ) -> str:
        """Build the full system prompt with language instructions.

        Steps:
        1. Add prominent language instruction at the top
        2. Inject common instructions from _common.md (if placeholder present)
        3. Add markdown language instruction for specific agents
        4. Add HITL question language instruction
        5. Inject dynamic tool descriptions from MCP config
        6. Add shared tool usage instructions (format depends on LLM capabilities)
        7. Add language footer reminder

        Args:
            language: Conversational language code (nl, en, etc.)
            supports_native_tools: Whether the LLM supports native tool calling
        """
        base_prompt = self.definition.system_prompt

        # 1. Add prominent language instruction at the top
        base_prompt = self._build_language_header(language) + base_prompt

        # 2. Inject common instructions (shared across agents)
        common_prompt = AgentDefinitionLoader.load_common_prompt()
        if common_prompt and "[COMMON_INSTRUCTIONS]" in base_prompt:
            base_prompt = base_prompt.replace("[COMMON_INSTRUCTIONS]", common_prompt)

        # 3. Inject markdown language instruction for specific agents
        markdown_instruction = self._get_markdown_language_instruction(language)
        if markdown_instruction:
            base_prompt += markdown_instruction

        # 4. Add HITL question language instruction
        lang_name = LANGUAGE_NAMES.get(language, language.upper())
        base_prompt += f"""

## HITL QUESTIONS LANGUAGE

All questions you ask via hitl_ask_question or hitl_ask_multiple_choice_question
MUST be written in {lang_name}. This is mandatory - never translate to or use
any other language for questions, regardless of examples you may see elsewhere.
"""

        # 5. Inject dynamic tool descriptions from MCP config
        if self.definition.mcps:
            tool_descriptions = generate_tool_descriptions(
                self.definition.get_mcp_names()
            )
            base_prompt = self._inject_tool_descriptions(base_prompt, tool_descriptions)

        # 6. Add tool usage instructions (router/planner are special)
        if self.agent_id in ("router", "planner"):
            if not supports_native_tools:
                base_prompt += self._get_xml_format_instructions()
        else:
            base_prompt += self._get_shared_tool_instructions(supports_native_tools)

        # 7. Language footer reminder
        base_prompt += f"\n\n!!! FINAL REMINDER: RESPOND IN {language.upper()} ONLY !!!\n"

        return base_prompt

    def build_user_prompt(
        self,
        prompt: str,
        context: dict = None,
        language: str = "nl",
    ) -> str:
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

    def _get_markdown_language_instruction(self, language: str) -> str:
        """Generate instruction for markdown file language.

        Business Analyst and Architect agents must always create markdown in Dutch.
        Other agents use the conversational language.
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

    # ------------------------------------------------------------------
    # Tool description injection
    # ------------------------------------------------------------------

    @staticmethod
    def _inject_tool_descriptions(prompt: str, tool_descriptions: str) -> str:
        """Inject dynamic tool descriptions into the system prompt.

        Looks for placeholder patterns or section markers and replaces/injects
        tool descriptions from mcp_config.yaml.
        """
        # Check for placeholder pattern
        if "[TOOL_DESCRIPTIONS_PLACEHOLDER]" in prompt:
            return prompt.replace("[TOOL_DESCRIPTIONS_PLACEHOLDER]", tool_descriptions)

        # Check for AVAILABLE TOOLS or TOOLS section
        for marker in ["AVAILABLE TOOLS:", "TOOLS:"]:
            if marker in prompt:
                lines = prompt.split("\n")
                new_lines = []
                skip_until_next_section = False

                for line in lines:
                    if marker in line:
                        new_lines.append(line)
                        new_lines.append(tool_descriptions)
                        skip_until_next_section = True
                    elif skip_until_next_section:
                        stripped = line.strip()
                        if stripped.startswith("===") or (
                            stripped.endswith(":") and stripped.isupper()
                        ):
                            skip_until_next_section = False
                            new_lines.append(line)
                    else:
                        new_lines.append(line)

                return "\n".join(new_lines)

        return prompt

    # ------------------------------------------------------------------
    # Tool usage instructions
    # ------------------------------------------------------------------

    @staticmethod
    def _get_xml_format_instructions() -> str:
        """Get XML format instructions for LLMs that don't support native tool calling."""
        return """

## TOOL CALL FORMAT

You MUST output tool calls using this XML format:
<tool_call>{"name": "tool_name", "arguments": {"arg1": "value1"}}</tool_call>

Example:
<tool_call>{"name": "done", "arguments": {"summary": "Agent deployer: Deployed at http://localhost:9101 (container: app-preview, port 9101:80)."}}</tool_call>
"""

    @staticmethod
    def _get_shared_tool_instructions(supports_native_tools: bool) -> str:
        """Get shared tool instructions appended to the system prompt.

        For LLMs with native tool calling: minimal instructions.
        For others: full instructions with XML format examples.
        """
        if supports_native_tools:
            return """

###############################################################################
#                    CRITICAL: TOOL USAGE INSTRUCTIONS                        #
###############################################################################

You are an AI agent that can ONLY interact through TOOL CALLS.
You MUST NOT output plain text - always use a tool.

## BUILT-IN TOOLS (always available)

1. **hitl_ask_question** - Ask the user a free-form question
   Required: question (string)
   Optional: context (string)

2. **hitl_ask_multiple_choice_question** - Ask user to select from options
   Required: question (string), choices (array of strings)
   Optional: allow_other (boolean)

3. **done** - Signal that your task is complete
   Required: summary (string) - DETAILED summary of what you accomplished including URLs, branch names, container names, file paths. NEVER just "Task completed".

## CRITICAL RULES

1. NEVER output plain text to communicate - use hitl_ask_question instead
2. NEVER announce what you will do - just call the tool directly
3. ALWAYS call done() when you have finished your task
4. Tool names use UNDERSCORES not colons (e.g., hitl_ask_question not hitl:ask_question)
"""
        else:
            return """

###############################################################################
#                    CRITICAL: TOOL USAGE INSTRUCTIONS                        #
###############################################################################

You are an AI agent that can ONLY interact through TOOL CALLS.
You MUST NOT output plain text - always use a tool.

## TOOL CALL FORMAT

You MUST output tool calls using this XML format:
<tool_call>{"name": "tool_name", "arguments": {"arg1": "value1", "arg2": "value2"}}</tool_call>

## EXAMPLES OF CORRECT TOOL CALLS

### Asking the user a question:
<tool_call>{"name": "hitl_ask_question", "arguments": {"question": "What database would you like me to use?"}}</tool_call>

### Asking a yes/no question:
<tool_call>{"name": "hitl_ask_multiple_choice_question", "arguments": {"question": "Should I proceed with this plan?", "choices": ["Yes", "No"]}}</tool_call>

### Signaling task completion:
<tool_call>{"name": "done", "arguments": {"summary": "Agent developer: Implemented counter app on branch feature/add-counter, pushed index.html, styles.css, Dockerfile."}}</tool_call>

## BUILT-IN TOOLS (always available)

1. **hitl_ask_question** - Ask the user a free-form question
   Required: question (string)
   Optional: context (string)

2. **hitl_ask_multiple_choice_question** - Ask user to select from options
   Required: question (string), choices (array of strings)
   Optional: allow_other (boolean)

3. **done** - Signal that your task is complete
   Required: summary (string) - DETAILED summary of what you accomplished including URLs, branch names, container names, file paths. NEVER just "Task completed".

## CRITICAL RULES

1. NEVER output plain text to communicate - use hitl_ask_question instead
2. NEVER announce what you will do - just call the tool directly
3. ALWAYS call done() when you have finished your task
4. Tool names use UNDERSCORES not colons (e.g., hitl_ask_question not hitl:ask_question)

## WRONG vs RIGHT

WRONG (plain text output):
```
I'll now create a file for you. What name would you like?
```

RIGHT (tool call):
```
<tool_call>{"name": "hitl_ask_question", "arguments": {"question": "What name would you like for the file?"}}</tool_call>
```

WRONG (announcing completion):
```
Done! I have completed the task.
```

RIGHT (tool call):
```
<tool_call>{"name": "done", "arguments": {"summary": "Agent developer: Created index.html and styles.css on branch main, pushed to remote."}}</tool_call>
```
"""

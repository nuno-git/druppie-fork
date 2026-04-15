"""HITL (Human-in-the-Loop) simulator for automated test execution."""
from __future__ import annotations

import logging
import time

from druppie.testing.schema import HITLProfile

logger = logging.getLogger(__name__)

MAX_HITL_INTERACTIONS = 100


class HITLSimulator:
    """Simulates human-in-the-loop answers using an LLM with a profile prompt."""

    def __init__(self, profile: HITLProfile, test_context: str = ""):
        self._profile = profile
        self._test_context = test_context
        self._interaction_count = 0

    def answer(self, question_text: str, choices: list[dict] | None = None) -> str:
        from druppie.llm.litellm_provider import ChatLiteLLM

        self._interaction_count += 1
        if self._interaction_count > MAX_HITL_INTERACTIONS:
            raise RuntimeError(f"Exceeded max HITL interactions ({MAX_HITL_INTERACTIONS})")

        llm = ChatLiteLLM(
            provider=self._profile.provider,
            model=self._profile.model,
            temperature=self._profile.temperature,
        )

        system_parts = [self._profile.prompt.strip()]
        if self._test_context:
            system_parts.append(f'\nContext: The user originally requested: "{self._test_context}"')
        system_parts.append(
            "\nWhen asked multiple choice questions, respond with the FULL TEXT of your chosen option, NOT a number."
            "\nWhen asked open-ended questions, give a clear 1-2 sentence answer."
        )
        system_prompt = "\n".join(system_parts)

        is_choice_question = bool(choices)
        if is_choice_question:
            choice_lines = []
            for i, c in enumerate(choices):
                text = c.get("text", c) if isinstance(c, dict) else str(c)
                choice_lines.append(f"{i + 1}. {text}")
            user_prompt = (
                f'The agent asks you a multiple choice question:\n\n'
                f'"{question_text}"\n\n'
                f'Options:\n'
                + "\n".join(choice_lines)
                + "\n\nRespond with the FULL TEXT of your chosen option, NOT a number."
            )
        else:
            user_prompt = (
                f'The agent asks you:\n\n'
                f'"{question_text}"\n\n'
                f'Respond with ONLY your answer, no explanation.'
            )

        # Retry on rate limits
        for attempt in range(5):
            try:
                response = llm.chat(
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ]
                )
                answer = response.content.strip()
                logger.info("HITL simulator answered (interaction %d): question=%s answer=%s",
                             self._interaction_count, question_text[:80], answer[:80])
                return answer
            except Exception as e:
                if "rate" in str(e).lower() and attempt < 4:
                    wait = 2 ** attempt
                    logger.warning("HITL simulator rate limited, retrying in %ds (attempt %d)", wait, attempt + 1)
                    time.sleep(wait)
                else:
                    raise

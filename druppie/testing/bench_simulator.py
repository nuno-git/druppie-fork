"""User simulator for HITL interactions in benchmark scenarios."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

from druppie.testing.bench_schema import UserSimulatorConfig

logger = logging.getLogger(__name__)


@dataclass
class SimulatedAnswer:
    """Record of a single simulated user answer."""

    answer: str
    mode_used: str  # "scripted", "llm", or "default"
    question: str
    interaction_number: int


class UserSimulator:
    """Simulates human-in-the-loop answers during benchmark runs.

    Supports three modes:
    - scripted: match question text against scripted patterns, fall back to default
    - llm: use a real LLM to generate answers (requires model config)
    - hybrid: try scripted first, then LLM for unmatched questions
    """

    def __init__(self, config: UserSimulatorConfig) -> None:
        self._config = config
        self._interaction_count = 0
        self._history: list[SimulatedAnswer] = []

    @property
    def history(self) -> list[SimulatedAnswer]:
        """Return a copy of the interaction history."""
        return list(self._history)

    @property
    def interaction_count(self) -> int:
        """Return the number of interactions so far."""
        return self._interaction_count

    def answer(
        self,
        question: str,
        choices: list[str] | None = None,
        context: str | None = None,
    ) -> str:
        """Produce a simulated answer for the given question.

        Args:
            question: The question the agent is asking the user.
            choices: Optional list of choices (for multiple-choice questions).
            context: Optional additional context about the conversation.

        Returns:
            The simulated user answer.

        Raises:
            RuntimeError: If max_interactions has been exceeded.
            ValueError: If in llm/hybrid mode and no model is configured.
        """
        self._interaction_count += 1
        if self._interaction_count > self._config.max_interactions:
            raise RuntimeError(
                f"Exceeded max_interactions ({self._config.max_interactions})"
            )

        # Try scripted (for scripted and hybrid modes)
        if self._config.mode in ("scripted", "hybrid"):
            scripted = self._try_scripted(question)
            if scripted is not None:
                self._record(scripted, "scripted", question)
                return scripted

        # Try LLM (for llm and hybrid modes)
        if self._config.mode in ("llm", "hybrid"):
            llm_answer = self._call_llm(question, choices, context)
            self._record(llm_answer, "llm", question)
            return llm_answer

        # Fallback: default answer
        self._record(self._config.default_answer, "default", question)
        return self._config.default_answer

    def _record(self, answer: str, mode: str, question: str) -> None:
        """Append an interaction record to the history."""
        self._history.append(
            SimulatedAnswer(
                answer=answer,
                mode_used=mode,
                question=question,
                interaction_number=self._interaction_count,
            )
        )

    def _try_scripted(self, question: str) -> str | None:
        """Try to match the question against scripted answer patterns.

        Matching is case-insensitive. The first matching pattern wins.
        """
        q_lower = question.lower()
        for s in self._config.scripted_answers:
            if s.question_contains.lower() in q_lower:
                return s.answer
        return None

    def _call_llm(
        self,
        question: str,
        choices: list[str] | None = None,
        context: str | None = None,
    ) -> str:
        """Generate an answer using a real LLM.

        Raises:
            ValueError: If no model is configured.
        """
        if not self._config.model:
            raise ValueError("UserSimulator in llm/hybrid mode requires 'model'")

        from druppie.llm.litellm_provider import ChatLiteLLM

        llm = ChatLiteLLM(
            provider=os.getenv("LLM_PROVIDER", "zai"),
            model=self._config.model,
            temperature=0.7,
        )

        system = (
            "You are simulating a human user answering questions from an AI agent."
        )
        if self._config.persona:
            system += f"\n\nYour persona:\n{self._config.persona}"

        user_prompt = f"The agent asks you:\n\n{question}"
        if choices:
            user_prompt += "\n\nChoices:\n" + "\n".join(
                f"  {i + 1}. {c}" for i, c in enumerate(choices)
            )
        if context:
            user_prompt += f"\n\nContext:\n{context}"
        if self._history:
            user_prompt += "\n\nPrevious Q&A:\n" + "\n".join(
                f"Q: {h.question}\nA: {h.answer}" for h in self._history
            )
        user_prompt += "\n\nRespond with ONLY your answer, no explanation."

        response = llm.chat(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ]
        )
        return response.content.strip()

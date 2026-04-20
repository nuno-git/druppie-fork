"""HITL (Human-in-the-Loop) simulator for automated test execution."""
from __future__ import annotations

import json
import logging
import re
import time

from druppie.testing.schema import HITLProfile

logger = logging.getLogger(__name__)

MAX_HITL_INTERACTIONS = 100


class HITLSimulator:
    """Simulates human-in-the-loop answers using an LLM with a profile prompt.

    Also decides approval/rejection on approval gates — the same persona
    both answers HITL questions and acts as the session owner reviewing
    tool calls, so its behavior stays coherent across a session.
    """

    def __init__(self, profile: HITLProfile, test_context: str = ""):
        self._profile = profile
        self._test_context = test_context
        self._interaction_count = 0

    # ------------------------------------------------------------------ #
    # HITL question answering
    # ------------------------------------------------------------------ #

    def answer(
        self,
        question_text: str,
        choices: list[dict] | None = None,
        question_context: str | None = None,
        session_transcript: str | None = None,
    ) -> str:
        from druppie.llm.litellm_provider import ChatLiteLLM

        self._interaction_count += 1
        if self._interaction_count > MAX_HITL_INTERACTIONS:
            raise RuntimeError(f"Exceeded max HITL interactions ({MAX_HITL_INTERACTIONS})")

        llm = ChatLiteLLM(
            provider=self._profile.provider,
            model=self._profile.model,
            temperature=self._profile.temperature,
        )

        system_prompt = self._build_system_prompt(
            extra_guidance=(
                "When asked multiple choice questions, respond with the FULL TEXT "
                "of your chosen option, NOT a number.\n"
                "When asked open-ended questions, give a clear 1-2 sentence answer."
            )
        )

        blocks = []
        if session_transcript:
            blocks.append(
                "Conversation so far (most recent tool calls, questions, approvals):\n\n"
                f"{session_transcript}\n"
            )
        if question_context:
            blocks.append(
                f"Additional context the agent provided with this question:\n\n{question_context}\n"
            )

        is_choice_question = bool(choices)
        if is_choice_question:
            choice_lines = []
            for i, c in enumerate(choices):
                text = c.get("text", c) if isinstance(c, dict) else str(c)
                choice_lines.append(f"{i + 1}. {text}")
            user_prompt = (
                "\n\n".join(blocks)
                + (f"\n\nThe agent asks you a multiple choice question:\n\n"
                   f'"{question_text}"\n\nOptions:\n'
                   + "\n".join(choice_lines)
                   + "\n\nRespond with the FULL TEXT of your chosen option, NOT a number.")
            )
        else:
            user_prompt = (
                "\n\n".join(blocks)
                + f"\n\nThe agent asks you:\n\n\"{question_text}\"\n\n"
                "Respond with ONLY your answer, no explanation."
            )

        response = self._call_llm_with_retry(
            llm,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        answer = response.content.strip()
        logger.info(
            "HITL simulator answered (interaction %d): question=%s answer=%s",
            self._interaction_count, question_text[:80], answer[:80],
        )
        return answer

    # ------------------------------------------------------------------ #
    # Approval gate decision
    # ------------------------------------------------------------------ #

    def decide_approval(
        self,
        tool_name: str,
        tool_arguments: dict | None,
        session_transcript: str | None = None,
    ) -> dict:
        """Let the persona approve or reject a pending approval gate.

        Returns a dict: {"status": "approved"|"rejected", "reason": str|None}.
        The reason is populated only for rejections and is what the agent
        will see in the tool call failure message.
        """
        from druppie.llm.litellm_provider import ChatLiteLLM

        self._interaction_count += 1
        if self._interaction_count > MAX_HITL_INTERACTIONS:
            raise RuntimeError(f"Exceeded max HITL interactions ({MAX_HITL_INTERACTIONS})")

        llm = ChatLiteLLM(
            provider=self._profile.provider,
            model=self._profile.model,
            temperature=self._profile.temperature,
        )

        system_prompt = self._build_system_prompt(
            extra_guidance=(
                "You are acting as the session owner reviewing an agent's tool call "
                "that requires your approval. Decide whether to APPROVE or REJECT it "
                "based on your persona and the conversation so far.\n\n"
                "Respond with ONLY valid JSON in this exact shape — no prose, no code "
                "fences:\n"
                "  {\"status\": \"approved\"}\n"
                "  or\n"
                "  {\"status\": \"rejected\", \"reason\": \"<concrete feedback for the agent>\"}\n\n"
                "If rejecting, the `reason` must give the agent actionable guidance so "
                "it can revise and try again. Do not reject without a reason."
            )
        )

        args_str = ""
        if tool_arguments:
            try:
                args_str = json.dumps(tool_arguments, ensure_ascii=False, indent=2)
            except Exception:
                args_str = str(tool_arguments)
            if len(args_str) > 8000:
                args_str = args_str[:8000] + f"\n... [truncated, {len(args_str) - 8000} chars omitted]"

        blocks = []
        if session_transcript:
            blocks.append(
                "Conversation so far (most recent tool calls, questions, approvals):\n\n"
                f"{session_transcript}\n"
            )
        blocks.append(
            f"The agent now wants to call `{tool_name}` with these arguments:\n\n"
            f"{args_str or '(no arguments)'}"
        )
        blocks.append(
            "Decide: approve or reject? Return JSON only."
        )
        user_prompt = "\n\n".join(blocks)

        response = self._call_llm_with_retry(
            llm,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )

        decision = self._parse_approval_decision(response.content)
        logger.info(
            "HITL simulator approval decision (interaction %d): tool=%s status=%s reason=%s",
            self._interaction_count, tool_name, decision["status"],
            (decision.get("reason") or "")[:120],
        )
        return decision

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _build_system_prompt(self, extra_guidance: str) -> str:
        parts = [self._profile.prompt.strip()]
        if self._test_context:
            parts.append(f'\nContext: The user originally requested: "{self._test_context}"')
        parts.append("\n" + extra_guidance)
        return "\n".join(parts)

    def _call_llm_with_retry(self, llm, messages):
        for attempt in range(5):
            try:
                return llm.chat(messages=messages)
            except Exception as e:
                if "rate" in str(e).lower() and attempt < 4:
                    wait = 2 ** attempt
                    logger.warning(
                        "HITL simulator rate limited, retrying in %ds (attempt %d)",
                        wait, attempt + 1,
                    )
                    time.sleep(wait)
                else:
                    raise

    @staticmethod
    def _parse_approval_decision(raw: str) -> dict:
        """Parse the LLM's approval decision JSON, tolerant of fences/prose."""
        text = (raw or "").strip()

        # Strip ```json fences if present
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)

        # First try the whole thing
        for candidate in (text, _extract_first_json_object(text)):
            if not candidate:
                continue
            try:
                obj = json.loads(candidate)
            except Exception:
                continue
            status = str(obj.get("status", "")).strip().lower()
            if status in ("approved", "approve", "yes"):
                return {"status": "approved", "reason": None}
            if status in ("rejected", "reject", "no"):
                reason = str(obj.get("reason") or "").strip() or "Rejected by session owner."
                return {"status": "rejected", "reason": reason}

        # Fallback: look for explicit approve/reject keywords
        low = text.lower()
        if "rejected" in low or "reject" in low:
            return {
                "status": "rejected",
                "reason": "Rejected (simulator could not parse structured decision).",
            }
        logger.warning("HITL simulator approval output unparsable — defaulting to approved: %r", raw[:200])
        return {"status": "approved", "reason": None}


def _extract_first_json_object(text: str) -> str | None:
    """Best-effort extraction of the first {...} block in `text`."""
    if not text:
        return None
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start != -1:
                return text[start : i + 1]
    return None

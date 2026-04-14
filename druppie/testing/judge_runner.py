"""LLM judge runner for evaluating agent execution traces."""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session as DbSession

from druppie.db.models import AgentRun, Message, ToolCall
from druppie.testing.schema import JudgeProfile

logger = logging.getLogger(__name__)


@dataclass
class JudgeCheckResult:
    check: str
    passed: bool
    reasoning: str
    source: str  # "check" or "inline"
    raw_input: str = ""   # prompt sent to judge LLM
    raw_output: str = ""  # raw response from judge LLM


class JudgeRunner:
    """Runs LLM judge checks against agent execution traces."""

    def __init__(self, profile: JudgeProfile):
        self._profile = profile

    def run_checks(self, db: DbSession, session_id: UUID,
                   judge_checks: list,
                   context: str | list[str] = "all", source: str = "check") -> list[JudgeCheckResult]:
        """Run judge checks. judge_checks is a list of JudgeCheck objects."""
        agent_trace = self._extract_agent_trace(db, session_id, context)
        if not agent_trace:
            return [
                JudgeCheckResult(check=jc.check, passed=False,
                                 reasoning=f"No execution trace found",
                                 source=source)
                for jc in judge_checks
            ]

        results = []
        for jc in judge_checks:
            judge_passed, reasoning, raw_input, raw_output = self._run_single_check(jc.check, agent_trace)

            if jc.is_eval:
                # Judge Eval — we're testing the judge itself
                final_passed = (judge_passed == jc.expected)
                expected_label = "PASS" if jc.expected else "FAIL"
                actual_label = "PASS" if judge_passed else "FAIL"
                reasoning = f"[Judge Eval: expected {expected_label}, got {actual_label}] {reasoning}"
                result_source = "judge_eval"
            else:
                # LLM Judge — verdict IS the result
                final_passed = judge_passed
                result_source = source

            results.append(JudgeCheckResult(
                check=jc.check, passed=final_passed, reasoning=reasoning, source=result_source,
                raw_input=raw_input, raw_output=raw_output,
            ))
        return results

    def _extract_agent_trace(self, db: DbSession, session_id: UUID,
                             context: str | list[str] = "all") -> str:
        """Extract execution trace for the judge.

        context can be:
        - "all": all agent runs in the session
        - "business_analyst": all runs of that agent
        - ["business_analyst", "architect"]: all runs of those agents
        """
        user_message = (
            db.query(Message)
            .filter(Message.session_id == session_id, Message.role == "user")
            .order_by(Message.sequence_number.asc())
            .first()
        )

        # Determine which agent runs to include
        if context == "all":
            agent_runs = (
                db.query(AgentRun)
                .filter(AgentRun.session_id == session_id)
                .order_by(AgentRun.sequence_number.asc())
                .all()
            )
        else:
            agent_ids = [context] if isinstance(context, str) else context
            agent_runs = (
                db.query(AgentRun)
                .filter(
                    AgentRun.session_id == session_id,
                    AgentRun.agent_id.in_(agent_ids),
                )
                .order_by(AgentRun.sequence_number.asc())
                .all()
            )

        if not agent_runs:
            return ""

        lines = []
        if user_message:
            lines.append(f'User message: "{user_message.content}"')
            lines.append("")

        for agent_run in agent_runs:
            tool_calls = (
                db.query(ToolCall)
                .filter(ToolCall.agent_run_id == agent_run.id)
                .order_by(ToolCall.created_at.asc())
                .all()
            )

            lines.append(f"Agent: {agent_run.agent_id} (run #{agent_run.sequence_number}, status: {agent_run.status})")
            if tool_calls:
                lines.append("Tool calls (in execution order):")
                for idx, tc in enumerate(tool_calls):
                    args_str = json.dumps(tc.arguments) if tc.arguments else "{}"
                    result_part = f" -> {tc.status or 'pending'}"
                    if tc.result:
                        result_part = f" -> {tc.result[:500]}"
                    if tc.error_message:
                        result_part += f" [error: {tc.error_message[:200]}]"
                    lines.append(f"  [{idx}] {tc.mcp_server}:{tc.tool_name}({args_str}){result_part}")
            else:
                lines.append("  (no tool calls)")
            lines.append("")

        return "\n".join(lines)

    def _run_single_check(self, check: str, agent_trace: str) -> tuple[bool, str, str, str]:
        from druppie.llm.litellm_provider import ChatLiteLLM

        llm = ChatLiteLLM(
            provider=self._profile.provider,
            model=self._profile.model,
            temperature=0.0,
        )

        prompt = f"""You are evaluating an AI agent's behavior.

The following trace shows the user's original message and the agent's execution (tool calls and results):

---
{agent_trace}
---

Evaluate this check:
{check}

Respond with JSON: {{"pass": true/false, "reasoning": "your explanation"}}"""

        messages = [
            {"role": "system", "content": "You are an evaluation judge. Respond ONLY with valid JSON."},
            {"role": "user", "content": prompt},
        ]

        for attempt in range(5):
            try:
                response = llm.chat(messages=messages)
                passed, reasoning = self._parse_judge_response(response.content)
                return passed, reasoning, prompt, response.content
            except Exception as e:
                if "rate" in str(e).lower() and attempt < 4:
                    wait = 2 ** attempt
                    logger.warning("Judge rate limited, retrying in %ds (attempt %d)", wait, attempt + 1)
                    time.sleep(wait)
                else:
                    logger.error("Judge check failed: check=%s error=%s", check[:80], str(e))
                    return False, f"Judge call failed: {e}", prompt, ""
        return False, "Judge call failed after retries", prompt, ""

    @staticmethod
    def _parse_judge_response(response_text: str) -> tuple[bool, str]:
        try:
            text = response_text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text
                text = text.rsplit("```", 1)[0]
            data = json.loads(text)
            if not isinstance(data, dict):
                return False, f"Judge response is not a JSON object: {response_text[:200]}"
            passed = bool(data.get("pass", False))
            reasoning = str(data.get("reasoning", ""))
            return passed, reasoning
        except (json.JSONDecodeError, ValueError):
            logger.warning("Judge response parse failed: response=%s", response_text[:200])
            return False, f"Failed to parse judge response: {response_text[:200]}"

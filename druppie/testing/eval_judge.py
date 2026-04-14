"""LLM-as-Judge evaluation engine.

Loads evaluation definitions from YAML, extracts context from DB,
calls a judge LLM, parses scores, and stores results.
"""

import logging
from pathlib import Path
from uuid import UUID

import yaml
from sqlalchemy.orm import Session as DbSession

from druppie.db.models import AgentRun, BenchmarkRun, EvaluationResult, LlmCall
from druppie.testing.eval_context import extract_context
from druppie.testing.eval_schema import EvaluationDefinition, EvaluationFile

logger = logging.getLogger(__name__)


class JudgeEngine:
    """Executes evaluation rubrics against completed agent runs."""

    def __init__(self, evaluations_dir: Path | None = None):
        self._evaluations_dir = evaluations_dir or (
            Path(__file__).resolve().parents[2] / "testing" / "evals"
        )
        self._definitions: dict[str, EvaluationDefinition] = {}
        self._load_definitions()

    def _load_definitions(self) -> None:
        for path in sorted(self._evaluations_dir.rglob("*.yaml")):
            data = yaml.safe_load(path.read_text())
            if not isinstance(data, dict) or "evaluation" not in data:
                # Skip v2-format eval files (use 'eval' key, not 'evaluation')
                logger.debug("Skipping non-v1 eval file: %s", path)
                continue
            try:
                parsed = EvaluationFile(**data)
                self._definitions[parsed.evaluation.name] = parsed.evaluation
            except Exception as exc:
                logger.warning("Failed to parse eval file %s: %s", path, exc, exc_info=True)

    @property
    def available_evaluations(self) -> list[str]:
        return sorted(self._definitions.keys())

    def evaluate(
        self,
        db: DbSession,
        session_id: UUID,
        evaluation_name: str,
        benchmark_run_id: UUID,
        judge_model_override: str | None = None,
        call_judge_fn=None,  # For testing: inject a mock judge function
    ) -> list[EvaluationResult]:
        """Run all rubrics in an evaluation against a session's agent run."""

        evaluation = self._definitions.get(evaluation_name)
        if evaluation is None:
            raise KeyError(
                f"Unknown evaluation: {evaluation_name}. "
                f"Available: {self.available_evaluations}"
            )

        # Find the target agent's last completed run in this session
        agent_run = (
            db.query(AgentRun)
            .filter(
                AgentRun.session_id == session_id,
                AgentRun.agent_id == evaluation.target_agent,
                AgentRun.status == "completed",
            )
            .order_by(AgentRun.sequence_number.desc())
            .first()
        )
        if agent_run is None:
            raise ValueError(
                f"No completed run for agent '{evaluation.target_agent}' "
                f"in session {session_id}"
            )

        # Get the LLM model/provider the agent used (from its LlmCall records)
        llm_call = (
            db.query(LlmCall)
            .filter(LlmCall.agent_run_id == agent_run.id)
            .first()
        )
        agent_llm_model = llm_call.model if llm_call else None
        agent_llm_provider = llm_call.provider if llm_call else None

        judge_model = judge_model_override or evaluation.judge_model

        results = []
        for rubric in evaluation.rubrics:
            # Merge evaluation-level and rubric-level context sources
            all_sources = evaluation.context + rubric.context_extra

            # Extract context from DB
            context = extract_context(
                db=db,
                agent_run_id=agent_run.id,
                session_id=session_id,
                agent_id=evaluation.target_agent,
                sources=all_sources,
            )

            # Render prompt template
            prompt = self._render_prompt(rubric.prompt, context)

            # Call judge LLM (or mock)
            if call_judge_fn:
                response_text, duration_ms, tokens_used = call_judge_fn(
                    prompt, judge_model
                )
            else:
                response_text, duration_ms, tokens_used = self._call_judge(
                    prompt, judge_model
                )

            # Parse score
            score_binary, score_graded, max_score, reasoning = self._parse_score(
                response_text, rubric.scoring
            )

            # Create result record
            result = EvaluationResult(
                benchmark_run_id=benchmark_run_id,
                session_id=session_id,
                agent_run_id=agent_run.id,
                agent_id=evaluation.target_agent,
                evaluation_name=evaluation_name,
                rubric_name=rubric.name,
                score_type=rubric.scoring,
                score_binary=score_binary,
                score_graded=score_graded,
                max_score=max_score,
                judge_model=judge_model,
                judge_prompt=prompt,
                judge_response=response_text,
                judge_reasoning=reasoning,
                llm_model=agent_llm_model,
                llm_provider=agent_llm_provider,
                judge_duration_ms=duration_ms,
                judge_tokens_used=tokens_used,
            )
            db.add(result)
            results.append(result)

        db.flush()
        return results

    def _render_prompt(self, template: str, context: dict[str, str]) -> str:
        result = template
        for key, value in context.items():
            result = result.replace("{{" + key + "}}", str(value))
        return result

    def _call_judge(
        self, prompt: str, judge_model: str
    ) -> tuple[str, int, int]:
        """Call judge LLM. Returns (response_text, duration_ms, tokens_used)."""
        import os

        from druppie.testing.utils import call_judge_llm

        return call_judge_llm(
            prompt=prompt,
            model=judge_model,
            provider=os.getenv("LLM_PROVIDER", "zai"),
        )

    def _parse_score(self, response: str, scoring: str) -> tuple:
        """Parse judge JSON response into score fields.

        Returns: (score_binary, score_graded, max_score, reasoning)
        """
        from druppie.testing.utils import parse_json_from_llm

        data = parse_json_from_llm(response)
        if data is None:
            return (
                None,
                None,
                None,
                f"Failed to parse judge response: {response[:200]}",
            )

        reasoning = str(data.get("reasoning", ""))

        if scoring == "binary":
            passed = data.get("pass", False)
            return bool(passed), None, None, reasoning
        else:
            raw_score = data.get("score", 0)
            try:
                score = float(raw_score)
            except (TypeError, ValueError):
                logger.warning("Judge score is not numeric: %s", raw_score)
                return None, 0.0, 5.0, f"Invalid score value '{raw_score}': {reasoning}"
            return None, score, 5.0, reasoning

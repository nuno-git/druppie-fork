"""Live background evaluation of completed agent runs."""

import logging
import subprocess
from datetime import datetime, timezone
from uuid import UUID

from druppie.db.models import BenchmarkRun
from druppie.testing.eval_config import get_evaluation_config
from druppie.testing.eval_judge import JudgeEngine

logger = logging.getLogger(__name__)


async def run_live_evaluation(
    session_id: UUID,
    agent_run_id: UUID,
    agent_id: str,
) -> None:
    """Evaluate a completed agent run in the background.

    Creates its own DB session. All exceptions are caught and logged
    — this must never affect agent execution.
    """
    from druppie.db.database import SessionLocal

    config = get_evaluation_config()
    evaluations = config.get_evaluations(agent_id)
    if not evaluations:
        return

    db = SessionLocal()
    try:
        git_commit, git_branch = _git_info()

        benchmark_run = BenchmarkRun(
            name=f"live-{agent_id}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
            run_type="live",
            git_commit=git_commit,
            git_branch=git_branch,
            judge_model=config.judge_model,
            config_summary=f"agent={agent_id}, evaluations={evaluations}",
            started_at=datetime.now(timezone.utc),
        )
        db.add(benchmark_run)
        db.flush()

        judge = JudgeEngine()
        for eval_name in evaluations:
            try:
                judge.evaluate(
                    db=db,
                    session_id=session_id,
                    evaluation_name=eval_name,
                    benchmark_run_id=benchmark_run.id,
                    judge_model_override=config.judge_model,
                )
            except Exception:
                logger.exception(
                    "Live evaluation rubric failed: %s for agent %s",
                    eval_name,
                    agent_id,
                )

        benchmark_run.completed_at = datetime.now(timezone.utc)
        db.commit()
        logger.info(
            "Live evaluation completed for agent %s in session %s",
            agent_id,
            session_id,
        )
    except Exception:
        logger.exception(
            "Live evaluation failed for agent %s in session %s",
            agent_id,
            session_id,
        )
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


def _git_info() -> tuple[str | None, str | None]:
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()[:40]
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        return commit, branch
    except Exception:
        return None, None

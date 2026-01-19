"""File-based storage for plans.

Simple JSON file storage - good for development and small deployments.
"""

import shutil
from datetime import datetime
from pathlib import Path

import aiofiles
import structlog

from druppie.core.models import Plan

logger = structlog.get_logger()


class FileStore:
    """File-based storage for Druppie plans.

    Structure:
        .druppie/
        └── plans/
            └── {plan_id}/
                ├── plan.json       # Plan metadata and status
                ├── logs/           # Execution logs
                │   └── step_{id}.log
                └── files/          # Generated files for this plan
    """

    def __init__(self, base_path: str | Path = ".druppie"):
        self.base_path = Path(base_path)
        self._ensure_directories()

    def _ensure_directories(self) -> None:
        """Create required directories."""
        (self.base_path / "plans").mkdir(parents=True, exist_ok=True)

    def get_plan_dir(self, plan_id: str) -> Path:
        """Get the directory for a plan."""
        return self.base_path / "plans" / plan_id

    def get_plan_files_dir(self, plan_id: str) -> Path:
        """Get the files directory for a plan's generated files."""
        files_dir = self.get_plan_dir(plan_id) / "files"
        files_dir.mkdir(parents=True, exist_ok=True)
        return files_dir

    def get_plan_logs_dir(self, plan_id: str) -> Path:
        """Get the logs directory for a plan."""
        logs_dir = self.get_plan_dir(plan_id) / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        return logs_dir

    def _ensure_plan_directories(self, plan_id: str) -> None:
        """Create directories for a plan."""
        plan_dir = self.get_plan_dir(plan_id)
        plan_dir.mkdir(parents=True, exist_ok=True)
        (plan_dir / "files").mkdir(exist_ok=True)
        (plan_dir / "logs").mkdir(exist_ok=True)

    # --- Plans ---

    async def save_plan(self, plan: Plan) -> None:
        """Save a plan to storage."""
        plan.updated_at = datetime.utcnow()

        # Ensure plan directory structure exists
        self._ensure_plan_directories(plan.id)

        # Save plan.json in the plan directory
        path = self.get_plan_dir(plan.id) / "plan.json"

        async with aiofiles.open(path, "w") as f:
            await f.write(plan.model_dump_json(indent=2))

        logger.debug("Plan saved", plan_id=plan.id)

    async def get_plan(self, plan_id: str) -> Plan | None:
        """Get a plan by ID."""
        # New structure: plans/{plan_id}/plan.json
        path = self.get_plan_dir(plan_id) / "plan.json"

        # Fallback to old structure for migration: plans/{plan_id}.json
        if not path.exists():
            old_path = self.base_path / "plans" / f"{plan_id}.json"
            if old_path.exists():
                path = old_path

        if not path.exists():
            return None

        async with aiofiles.open(path) as f:
            data = await f.read()
            return Plan.model_validate_json(data)

    async def list_plans(
        self,
        status: str | None = None,
        workflow_id: str | None = None,
        limit: int = 100,
    ) -> list[Plan]:
        """List plans, optionally filtered."""
        plans = []
        plans_dir = self.base_path / "plans"

        # List plan directories (new structure)
        plan_dirs = [d for d in plans_dir.iterdir() if d.is_dir()]

        # Also check for old-style .json files
        plan_files = list(plans_dir.glob("*.json"))

        # Combine and sort by modification time
        all_paths = []
        for d in plan_dirs:
            plan_json = d / "plan.json"
            if plan_json.exists():
                all_paths.append(plan_json)
        all_paths.extend(plan_files)

        all_paths.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        for path in all_paths:
            if len(plans) >= limit:
                break

            async with aiofiles.open(path) as f:
                data = await f.read()
                plan = Plan.model_validate_json(data)

                # Apply filters
                if status and plan.status.value != status:
                    continue
                if workflow_id and plan.workflow_id != workflow_id:
                    continue

                plans.append(plan)

        return plans

    async def delete_plan(self, plan_id: str) -> bool:
        """Delete a plan and its workspace."""
        plan_dir = self.get_plan_dir(plan_id)

        # New structure: delete entire directory
        if plan_dir.exists() and plan_dir.is_dir():
            shutil.rmtree(plan_dir)
            logger.info("Plan deleted", plan_id=plan_id)
            return True

        # Fallback: old structure
        old_path = self.base_path / "plans" / f"{plan_id}.json"
        if old_path.exists():
            old_path.unlink()
            logger.info("Plan deleted", plan_id=plan_id)
            return True

        return False

    async def save_step_log(self, plan_id: str, step_id: int, log_content: str) -> None:
        """Save execution log for a step."""
        logs_dir = self.get_plan_logs_dir(plan_id)
        log_path = logs_dir / f"step_{step_id}.log"

        async with aiofiles.open(log_path, "a") as f:
            timestamp = datetime.utcnow().isoformat()
            await f.write(f"[{timestamp}] {log_content}\n")

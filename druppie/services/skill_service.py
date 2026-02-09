"""Skill service for discovering and loading skills.

Skills are markdown files with YAML frontmatter that get injected into
agent conversations when invoked.
"""

from pathlib import Path

import structlog
import yaml

from ..domain import SkillSummary, SkillDetail

logger = structlog.get_logger()

# Default skills directory relative to druppie package
SKILLS_DIR = Path(__file__).parent.parent / "skills"


class SkillService:
    """Service for skill discovery and loading."""

    def __init__(self, skills_dir: Path | None = None):
        """Initialize skill service.

        Args:
            skills_dir: Override skills directory (for testing)
        """
        self.skills_dir = skills_dir or SKILLS_DIR

    def discover_skills(self) -> list[SkillSummary]:
        """Scan skills directory and return all available skills.

        Returns:
            List of SkillSummary with name and description
        """
        skills = []

        if not self.skills_dir.exists():
            logger.warning("skills_dir_not_found", path=str(self.skills_dir))
            return skills

        for skill_dir in self.skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue

            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue

            try:
                frontmatter = self._parse_frontmatter(skill_file)
                skills.append(
                    SkillSummary(
                        name=frontmatter.get("name", skill_dir.name),
                        description=frontmatter.get("description", ""),
                    )
                )
            except Exception as e:
                logger.warning(
                    "skill_parse_error",
                    skill=skill_dir.name,
                    error=str(e),
                )

        return sorted(skills, key=lambda s: s.name)

    def get_skill(self, name: str) -> SkillDetail | None:
        """Load full skill content by name.

        Args:
            name: The skill name (directory name)

        Returns:
            SkillDetail with full prompt content, or None if not found
        """
        skill_dir = self.skills_dir / name
        skill_file = skill_dir / "SKILL.md"

        if not skill_file.exists():
            logger.warning("skill_not_found", name=name)
            return None

        try:
            frontmatter, content = self._parse_skill_file(skill_file)
            return SkillDetail(
                name=frontmatter.get("name", name),
                description=frontmatter.get("description", ""),
                prompt_content=content,
            )
        except Exception as e:
            logger.error("skill_load_error", name=name, error=str(e))
            return None

    def get_skills_for_agent(self, agent_skills: list[str]) -> list[SkillSummary]:
        """Get skills available to an agent.

        Args:
            agent_skills: List of skill names from agent YAML definition

        Returns:
            List of SkillSummary for skills that exist
        """
        available_skills = []

        for skill_name in agent_skills:
            skill = self.get_skill(skill_name)
            if skill:
                available_skills.append(
                    SkillSummary(name=skill.name, description=skill.description)
                )
            else:
                logger.warning(
                    "agent_skill_not_found",
                    skill=skill_name,
                )

        return available_skills

    def _parse_frontmatter(self, skill_file: Path) -> dict:
        """Parse YAML frontmatter from a skill file.

        Args:
            skill_file: Path to SKILL.md file

        Returns:
            Dictionary of frontmatter values
        """
        content = skill_file.read_text()
        if not content.startswith("---"):
            return {}

        # Find end of frontmatter
        end_idx = content.find("---", 3)
        if end_idx == -1:
            return {}

        frontmatter_yaml = content[3:end_idx].strip()
        return yaml.safe_load(frontmatter_yaml) or {}

    def _parse_skill_file(self, skill_file: Path) -> tuple[dict, str]:
        """Parse skill file into frontmatter and content.

        Args:
            skill_file: Path to SKILL.md file

        Returns:
            Tuple of (frontmatter dict, markdown content)
        """
        content = skill_file.read_text()

        if not content.startswith("---"):
            return {}, content

        # Find end of frontmatter
        end_idx = content.find("---", 3)
        if end_idx == -1:
            return {}, content

        frontmatter_yaml = content[3:end_idx].strip()
        frontmatter = yaml.safe_load(frontmatter_yaml) or {}

        # Content is everything after the second ---
        markdown_content = content[end_idx + 3:].strip()

        return frontmatter, markdown_content

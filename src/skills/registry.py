"""Skill registry: query, filter, and manage loaded skills."""

from __future__ import annotations

import logging
from pathlib import Path

from src.skills.loader import discover_with_product_overlay, load_skill_content
from src.skills.models import Skill, SkillMetadata

logger = logging.getLogger(__name__)


class SkillRegistry:
    """Central registry for discovering and querying skills.

    Skills are discovered from the filesystem at init time (L1 — metadata only).
    Content is lazy-loaded on first access (L2).
    """

    def __init__(self, skills_dir: str | Path, product: str | None = None):
        self.skills_dir = Path(skills_dir)
        self.product = product
        self._skills: list[Skill] = discover_with_product_overlay(skills_dir, product)

    @property
    def all_skills(self) -> list[Skill]:
        return self._skills

    def for_agent(self, agent_name: str) -> list[Skill]:
        """Return skills that apply to a specific agent, sorted by priority.

        A skill applies if:
        - Its `applies_to` list contains the agent_name, OR
        - Its `applies_to` list is empty (applies to all agents)
        """
        matched = [
            self._ensure_loaded(s)
            for s in self._skills
            if not s.applies_to or agent_name in s.applies_to
        ]
        return sorted(matched, key=lambda s: s.priority)

    def by_domain(self, domain: str) -> list[Skill]:
        """Return skills matching a specific domain."""
        return [
            self._ensure_loaded(s)
            for s in self._skills
            if s.metadata.domain == domain
        ]

    def by_name(self, name: str) -> Skill | None:
        """Look up a skill by exact name."""
        for s in self._skills:
            if s.name == name:
                return self._ensure_loaded(s)
        return None

    def by_tag(self, tag: str) -> list[Skill]:
        """Return skills that have a specific tag."""
        return [
            self._ensure_loaded(s)
            for s in self._skills
            if tag in s.metadata.tags
        ]

    def available_skills_summary(self) -> str:
        """Return a compact summary of all available skills (L1 data only).

        This is cheap to include in any system prompt (~50 tokens/skill).
        """
        if not self._skills:
            return "No skills available."

        lines = ["Available domain skills:"]
        for s in sorted(self._skills, key=lambda s: s.priority):
            agents = ", ".join(s.applies_to) if s.applies_to else "all"
            lines.append(f"- {s.name}: {s.metadata.description} (agents: {agents})")
        return "\n".join(lines)

    def reload(self) -> None:
        """Re-discover skills from the filesystem."""
        self._skills = discover_with_product_overlay(self.skills_dir, self.product)
        logger.info("Reloaded: %d skills", len(self._skills))

    def _ensure_loaded(self, skill: Skill) -> Skill:
        """Lazy-load skill content if not already loaded (L1 → L2)."""
        if not skill.is_loaded:
            load_skill_content(skill)
        return skill

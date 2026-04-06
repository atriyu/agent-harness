"""Skill injector: composes skills into agent system prompts.

Handles token budgeting, priority ordering, and formatting of skill
content sections within the system prompt.
"""

from __future__ import annotations

import logging

from src.skills.models import Skill
from src.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)

# Approximate tokens per character (conservative estimate)
_CHARS_PER_TOKEN = 4

SKILL_SECTION_HEADER = "\n\n---\n## Domain Skill: {name}\n\n"
SKILL_SECTION_FOOTER = "\n"


class SkillInjector:
    """Composes skills into agent system prompts with token budgeting."""

    def build_system_prompt(
        self,
        agent_name: str,
        core_prompt: str,
        registry: SkillRegistry,
        max_skill_tokens: int = 8000,
    ) -> str:
        """Build a complete system prompt from core prompt + matched skills.

        Args:
            agent_name: The agent requesting skills (used for filtering).
            core_prompt: The agent's minimal role/output-format prompt.
            registry: The skill registry to query.
            max_skill_tokens: Maximum tokens to allocate for skill content.

        Returns:
            Combined prompt: core_prompt + skill sections (within budget).
        """
        skills = registry.for_agent(agent_name)

        if not skills:
            return core_prompt

        # Build skill sections within token budget
        sections: list[str] = []
        tokens_used = 0

        for skill in skills:
            if not skill.content:
                continue

            section = (
                SKILL_SECTION_HEADER.format(name=skill.name)
                + skill.content
                + SKILL_SECTION_FOOTER
            )
            section_tokens = len(section) // _CHARS_PER_TOKEN

            if tokens_used + section_tokens > max_skill_tokens:
                logger.info(
                    "Skill budget exhausted for agent=%s after %d skills (%d tokens). "
                    "Skipping: %s",
                    agent_name, len(sections), tokens_used, skill.name,
                )
                break

            sections.append(section)
            tokens_used += section_tokens

        if sections:
            logger.info(
                "Injected %d skills into %s prompt (~%d tokens)",
                len(sections), agent_name, tokens_used,
            )

        # Compose: core prompt + skills summary + skill sections
        parts = [core_prompt]

        # Add L1 summary so the agent knows what skills exist
        summary = registry.available_skills_summary()
        if summary:
            parts.append(f"\n\n{summary}")

        parts.extend(sections)

        return "".join(parts)


def build_prompt_with_skills(
    agent_name: str,
    core_prompt: str,
    registry: SkillRegistry | None,
    max_skill_tokens: int = 8000,
) -> str:
    """Convenience function: build prompt with skills if registry is available,
    otherwise return core_prompt unchanged (backward-compatible).
    """
    if registry is None:
        return core_prompt
    return SkillInjector().build_system_prompt(
        agent_name=agent_name,
        core_prompt=core_prompt,
        registry=registry,
        max_skill_tokens=max_skill_tokens,
    )

"""Pydantic models for the Skills framework."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SkillMetadata(BaseModel):
    """Lightweight metadata parsed from YAML frontmatter (L1 — always loaded)."""

    name: str
    description: str = ""
    domain: str = ""
    applies_to: list[str] = Field(default_factory=list)  # Agent names
    priority: int = 10  # Lower = loaded first
    tags: list[str] = Field(default_factory=list)


class Skill(BaseModel):
    """A complete skill with metadata and content."""

    metadata: SkillMetadata
    content: str = ""  # Full markdown body (empty until L2 load)
    source_path: str = ""
    is_loaded: bool = False  # True once content has been read

    @property
    def name(self) -> str:
        return self.metadata.name

    @property
    def applies_to(self) -> list[str]:
        return self.metadata.applies_to

    @property
    def priority(self) -> int:
        return self.metadata.priority

    def token_estimate(self) -> int:
        """Rough token estimate: ~4 chars per token."""
        return len(self.content) // 4 if self.content else 0

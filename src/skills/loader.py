"""File-based skill discovery with progressive loading.

Scans a directory tree for markdown files with YAML frontmatter,
parses metadata at discovery time (L1), and lazy-loads content
on demand (L2).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml

from src.skills.models import Skill, SkillMetadata

logger = logging.getLogger(__name__)

# Regex to split YAML frontmatter from markdown body
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)", re.DOTALL)


def _parse_skill_file(path: Path) -> tuple[SkillMetadata, str] | None:
    """Parse a skill markdown file into metadata and body content."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("Failed to read skill file %s: %s", path, e)
        return None

    match = _FRONTMATTER_RE.match(text)
    if not match:
        logger.debug("No YAML frontmatter in %s, skipping", path)
        return None

    try:
        fm = yaml.safe_load(match.group(1))
        if not isinstance(fm, dict) or "name" not in fm:
            logger.debug("Invalid frontmatter in %s (missing 'name')", path)
            return None
        metadata = SkillMetadata.model_validate(fm)
        body = match.group(2).strip()
        return metadata, body
    except Exception as e:
        logger.warning("Failed to parse frontmatter in %s: %s", path, e)
        return None


def discover_skills(skills_dir: str | Path) -> list[Skill]:
    """Scan a directory tree for skill files and return them with metadata only (L1).

    Content is NOT loaded yet — call `load_skill_content()` to populate.
    """
    skills_path = Path(skills_dir)
    if not skills_path.exists():
        logger.info("Skills directory not found: %s", skills_path)
        return []

    skills: list[Skill] = []
    for md_file in sorted(skills_path.rglob("*.md")):
        result = _parse_skill_file(md_file)
        if result is None:
            continue
        metadata, _body = result
        # L1: metadata only, content deferred
        skills.append(Skill(
            metadata=metadata,
            content="",
            source_path=str(md_file),
            is_loaded=False,
        ))

    logger.info("Discovered %d skills in %s", len(skills), skills_path)
    return skills


def load_skill_content(skill: Skill) -> Skill:
    """Load the full markdown body for a skill (L1 → L2 transition)."""
    if skill.is_loaded:
        return skill

    path = Path(skill.source_path)
    if not path.exists():
        logger.warning("Skill file not found: %s", path)
        return skill

    result = _parse_skill_file(path)
    if result is None:
        return skill

    _metadata, body = result
    skill.content = body
    skill.is_loaded = True
    return skill


def discover_with_product_overlay(
    base_dir: str | Path,
    product: str | None = None,
) -> list[Skill]:
    """Discover skills with optional product-specific overlay.

    Product skills in `{base_dir}/products/{product}/` override or extend
    base skills with the same name.
    """
    skills = discover_skills(base_dir)

    if not product:
        return skills

    product_dir = Path(base_dir) / "products" / product
    if not product_dir.exists():
        logger.info("No product-specific skills for '%s'", product)
        return skills

    product_skills = discover_skills(product_dir)

    # Merge: product skills override base skills with the same name
    base_by_name = {s.name: s for s in skills}
    for ps in product_skills:
        base_by_name[ps.name] = ps

    merged = sorted(base_by_name.values(), key=lambda s: s.priority)
    logger.info("Merged %d base + %d product skills = %d total", len(skills), len(product_skills), len(merged))
    return merged

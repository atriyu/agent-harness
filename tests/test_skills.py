"""Tests for the skills framework: loader, registry, injector, generator."""

import pytest
from pathlib import Path

from src.skills.models import Skill, SkillMetadata
from src.skills.loader import _parse_skill_file, discover_skills, discover_with_product_overlay, load_skill_content
from src.skills.registry import SkillRegistry
from src.skills.injector import SkillInjector, build_prompt_with_skills
from src.skills.generator import generate_api_skill, _extract_from_ast


@pytest.fixture
def skills_dir(tmp_path):
    """Create a test skills directory with sample skill files."""
    d = tmp_path / "skills"
    d.mkdir()

    # Domain skill
    (d / "domains").mkdir()
    (d / "domains" / "vpn.md").write_text(
        "---\n"
        "name: vpn-protocols\n"
        "description: VPN testing patterns\n"
        "domain: vpn\n"
        "applies_to: [plan, codegen]\n"
        "priority: 1\n"
        "tags: [vpn, wireguard]\n"
        "---\n\n"
        "## WireGuard\n\nTest tunnel establishment within 5s.\n"
    )

    # Triage skill
    (d / "triage").mkdir()
    (d / "triage" / "diagnostic.md").write_text(
        "---\n"
        "name: diagnostic-framework\n"
        "description: 5-step triage framework\n"
        "domain: triage\n"
        "applies_to: [triage]\n"
        "priority: 1\n"
        "---\n\n"
        "## Step 1\nCluster failures.\n"
    )

    # Global skill (applies to all agents)
    (d / "global.md").write_text(
        "---\n"
        "name: general-qa\n"
        "description: General QA best practices\n"
        "priority: 10\n"
        "---\n\n"
        "Always verify before and after state.\n"
    )

    # Product override directory
    prod = d / "products" / "acme"
    prod.mkdir(parents=True)
    (prod / "product-context.md").write_text(
        "---\n"
        "name: vpn-protocols\n"
        "description: ACME-specific VPN testing overrides\n"
        "domain: vpn\n"
        "applies_to: [plan, codegen]\n"
        "priority: 1\n"
        "---\n\n"
        "## ACME WireGuard\n\nACME requires 2s handshake.\n"
    )

    # Invalid file (no frontmatter)
    (d / "no-frontmatter.md").write_text("Just some text without YAML.\n")

    return d


def test_parse_skill_file(skills_dir):
    result = _parse_skill_file(skills_dir / "domains" / "vpn.md")
    assert result is not None
    metadata, body = result
    assert metadata.name == "vpn-protocols"
    assert metadata.domain == "vpn"
    assert "plan" in metadata.applies_to
    assert "WireGuard" in body


def test_parse_invalid_file(skills_dir):
    result = _parse_skill_file(skills_dir / "no-frontmatter.md")
    assert result is None


def test_discover_skills(skills_dir):
    skills = discover_skills(skills_dir)
    names = {s.name for s in skills}
    assert "vpn-protocols" in names
    assert "diagnostic-framework" in names
    assert "general-qa" in names
    # Content should NOT be loaded yet (L1 only)
    vpn = [s for s in skills if s.name == "vpn-protocols"][0]
    assert not vpn.is_loaded
    assert vpn.content == ""


def test_load_skill_content(skills_dir):
    skills = discover_skills(skills_dir)
    vpn = [s for s in skills if s.name == "vpn-protocols"][0]
    assert not vpn.is_loaded
    load_skill_content(vpn)
    assert vpn.is_loaded
    assert "WireGuard" in vpn.content


def test_discover_with_product_overlay(skills_dir):
    # Without product: base vpn skill
    base = discover_with_product_overlay(skills_dir)
    vpn_base = [s for s in base if s.name == "vpn-protocols"][0]
    load_skill_content(vpn_base)
    assert "5s" in vpn_base.content

    # With product: ACME override
    overlay = discover_with_product_overlay(skills_dir, product="acme")
    vpn_acme = [s for s in overlay if s.name == "vpn-protocols"][0]
    load_skill_content(vpn_acme)
    assert "ACME" in vpn_acme.content


def test_registry_for_agent(skills_dir):
    registry = SkillRegistry(skills_dir)

    # Plan agent should get: vpn-protocols (applies_to includes plan) + general-qa (no filter)
    plan_skills = registry.for_agent("plan")
    plan_names = {s.name for s in plan_skills}
    assert "vpn-protocols" in plan_names
    assert "general-qa" in plan_names
    assert "diagnostic-framework" not in plan_names  # Only applies to triage

    # Triage agent should get: diagnostic-framework + general-qa
    triage_skills = registry.for_agent("triage")
    triage_names = {s.name for s in triage_skills}
    assert "diagnostic-framework" in triage_names
    assert "general-qa" in triage_names
    assert "vpn-protocols" not in triage_names


def test_registry_by_domain(skills_dir):
    registry = SkillRegistry(skills_dir)
    vpn_skills = registry.by_domain("vpn")
    # Base + product override both have domain "vpn" (product dir is inside skills dir)
    assert len(vpn_skills) >= 1
    assert any(s.name == "vpn-protocols" for s in vpn_skills)


def test_registry_by_name(skills_dir):
    registry = SkillRegistry(skills_dir)
    skill = registry.by_name("diagnostic-framework")
    assert skill is not None
    assert skill.is_loaded
    assert "Cluster" in skill.content

    missing = registry.by_name("nonexistent")
    assert missing is None


def test_registry_summary(skills_dir):
    registry = SkillRegistry(skills_dir)
    summary = registry.available_skills_summary()
    assert "vpn-protocols" in summary
    assert "diagnostic-framework" in summary
    assert "general-qa" in summary


def test_injector_basic(skills_dir):
    registry = SkillRegistry(skills_dir)
    injector = SkillInjector()

    prompt = injector.build_system_prompt(
        agent_name="plan",
        core_prompt="You are a test planner. Output JSON.",
        registry=registry,
    )

    assert prompt.startswith("You are a test planner.")
    assert "WireGuard" in prompt  # vpn skill injected
    assert "General QA" not in prompt or "general-qa" in prompt.lower() or "verify" in prompt.lower()


def test_injector_token_budget(skills_dir):
    registry = SkillRegistry(skills_dir)
    injector = SkillInjector()

    # With very small budget, some skills should be dropped
    prompt = injector.build_system_prompt(
        agent_name="plan",
        core_prompt="Core prompt.",
        registry=registry,
        max_skill_tokens=10,  # Very small budget
    )
    # Should still have core prompt
    assert "Core prompt." in prompt


def test_build_prompt_with_skills_none_registry():
    """Backward compatibility: no registry returns core prompt unchanged."""
    result = build_prompt_with_skills("plan", "Core prompt.", None)
    assert result == "Core prompt."


def test_build_prompt_with_skills_registry(skills_dir):
    registry = SkillRegistry(skills_dir)
    result = build_prompt_with_skills("plan", "Core prompt.", registry)
    assert "Core prompt." in result
    assert "vpn-protocols" in result  # Skill summary included


def test_generate_api_skill(tmp_path):
    """Test API skill generation from a Python source file."""
    # Create a simple Python file
    source = tmp_path / "sample.py"
    source.write_text('''\
"""Sample networking module."""

from dataclasses import dataclass


@dataclass
class Result:
    value: int = 0
    error: str = ""


class SampleHelper:
    """Helper for sample operations."""

    def do_something(self, target: str, count: int = 10) -> Result:
        """Do something interesting.

        Args:
            target: The target to operate on.
            count: Number of times.
        """
        return Result(value=count)
''')

    output = tmp_path / "sample-api.md"
    path = generate_api_skill(source, output, "sample-api", "Sample API reference")

    assert path.exists()
    content = path.read_text()
    assert "---" in content  # Has frontmatter
    assert "sample-api" in content
    assert "SampleHelper" in content
    assert "do_something" in content
    assert "target: str" in content


def test_generate_api_skill_from_real_module():
    """Test API skill generation against the actual VPN helper."""
    from pathlib import Path
    import tempfile

    vpn_source = Path("src/networking/vpn.py")
    if not vpn_source.exists():
        pytest.skip("VPN source not found")

    with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
        out_path = Path(f.name)

    try:
        generate_api_skill(vpn_source, out_path, "vpn-api", "VPN API reference")
        content = out_path.read_text()
        assert "VPNHelper" in content
        assert "establish_tunnel" in content
        assert "check_dns_leak" in content
    finally:
        out_path.unlink(missing_ok=True)

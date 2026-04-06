"""API Enhancement Agent: generates missing test helper API code.

Reads the gap report, the current helper source code, and domain skills,
then generates and applies the missing methods/parameters. Validates all
changes with ast.parse and regenerates API reference skills.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

from src.agents.base import BaseAgent
from src.artifacts.models import (
    APIEnhancement,
    EnhancementReport,
    GapReport,
)


class APIEnhanceAgent(BaseAgent):
    agent_name = "api_enhance"
    default_task_type = "api_enhancement"
    core_system_prompt = """\
You are a Python test infrastructure engineer. Your job is to add missing
capabilities to test helper modules.

These modules follow a consistent pattern:
- They wrap CLI tools (iperf3, tcpdump, wstunnel, testssl.sh, nmap, etc.)
- Each method builds a command string, executes it via self._exec(node, cmd), and parses output
- Return types are dataclasses with typed fields
- All execution happens on Containerlab topology nodes

When adding a new method or parameter:
1. Follow the EXACT patterns used by existing methods in the same file
2. Use self._exec(node, cmd, timeout=N) for command execution
3. Return a typed dataclass (create new ones if needed)
4. Add proper docstring with Args/Returns
5. Handle errors gracefully (try/except, return error in result object)
6. Parse CLI tool output into structured fields

When modifying an existing method to add a parameter:
1. Add the parameter with a default value (backward compatible)
2. Branch on the new parameter in the method body
3. Keep existing behavior unchanged when the new parameter is at its default

Output ONLY the complete updated Python source file. No markdown fences, no explanations.
"""

    async def run(self, inputs: Any) -> dict:
        store = inputs["store"]
        config = inputs["config"]

        # Load gap report
        gap_files = store.list_files("gap_analysis", "gap_report.json")
        if not gap_files:
            self.logger.info("No gap report found, skipping enhancement")
            return {"artifact_paths": [], "enhancement_report": None}

        gap_report = GapReport.model_validate_json(gap_files[-1].read_text())

        if not gap_report.gaps:
            self.logger.info("No API gaps to enhance")
            empty = EnhancementReport(gap_report_id=gap_report.plan_id, enhancements=[])
            return {"artifact_paths": [], "enhancement_report": empty}

        # Separate gaps: new modules vs enhancements to existing modules
        new_module_gaps: list = []
        existing_module_gaps: dict[str, list] = {}

        for gap in gap_report.gaps:
            if gap.gap_type.value in ("missing_tool", "missing_module"):
                new_module_gaps.append(gap)
            else:
                existing_module_gaps.setdefault(gap.module, []).append(gap)

        enhancements: list[APIEnhancement] = []

        # First: create new modules for missing tools/modules
        for gap in new_module_gaps:
            results = await self._create_new_module(gap, config)
            enhancements.extend(results)

        # Then: enhance existing modules
        for module_path, module_gaps in existing_module_gaps.items():
            results = await self._enhance_module(module_path, module_gaps, config)
            enhancements.extend(results)

        # Regenerate API reference skills
        api_skills_regenerated = self._regenerate_api_skills(config)

        report = EnhancementReport(
            gap_report_id=gap_report.plan_id,
            enhancements=enhancements,
            total_applied=sum(1 for e in enhancements if e.status == "applied"),
            total_failed=sum(1 for e in enhancements if e.status == "failed"),
            api_skills_regenerated=api_skills_regenerated,
        )

        path = store.save("gap_analysis", "enhancement_report.json", report)
        self.logger.info(
            "API enhancement: %d applied, %d failed, skills regenerated: %s",
            report.total_applied, report.total_failed, api_skills_regenerated,
        )

        return {"artifact_paths": [str(path)], "enhancement_report": report}

    async def _create_new_module(
        self, gap, config: dict,
    ) -> list[APIEnhancement]:
        """Create an entirely new helper module for a missing tool/capability."""
        target_path = gap.suggested_module or f"src/networking/{gap.tool_name or 'new_helper'}.py"
        src_path = Path(target_path)

        if src_path.exists():
            self.logger.info("Module %s already exists, treating as enhance", target_path)
            return await self._enhance_module(target_path, [gap], config)

        # Read an existing module as a reference for patterns
        reference_source = ""
        ref_path = Path("src/networking/traffic.py")
        if ref_path.exists():
            reference_source = ref_path.read_text()

        user_content = (
            f"## Task: Create New Helper Module\n\n"
            f"**Gap**: {gap.description}\n"
            f"**Tool**: {gap.tool_name or 'N/A'}\n"
            f"**Target file**: {target_path}\n"
            f"**Needed by tests**: {gap.test_ids}\n"
            f"**Blocks requirements**: {gap.req_ids}\n\n"
            f"## Reference Module (follow this pattern exactly):\n"
            f"```python\n{reference_source[:4000]}\n```\n\n"
            f"Create a complete, new Python module at {target_path} that:\n"
            f"1. Wraps the '{gap.tool_name}' CLI tool\n"
            f"2. Follows the EXACT same patterns as the reference module "
            f"(TopologyManager constructor, _exec method, dataclass return types)\n"
            f"3. Provides the capabilities described in the gap\n"
            f"4. Includes proper docstrings and type hints\n"
            f"5. Handles errors gracefully\n\n"
            f"Output ONLY the complete Python source file."
        )

        try:
            new_source = await self.llm_call(user_content=user_content)

            if new_source.startswith("```"):
                new_source = new_source.split("\n", 1)[1].rsplit("```", 1)[0]

            ast.parse(new_source)

            # Create parent directories if needed
            src_path.parent.mkdir(parents=True, exist_ok=True)
            src_path.write_text(new_source)

            self.logger.info("Created new module: %s (tool: %s)", target_path, gap.tool_name)

            return [APIEnhancement(
                gap_id=gap.gap_id,
                module_path=target_path,
                action="add_method",
                code_diff=f"Created new module {target_path} wrapping {gap.tool_name}",
                status="applied",
            )]

        except SyntaxError as e:
            self.logger.warning("Generated module has syntax error: %s", e)
            return [APIEnhancement(
                gap_id=gap.gap_id, module_path=target_path,
                action="add_method",
                code_diff=f"Syntax error in generated module: {e}",
                status="failed",
            )]
        except Exception as e:
            self.logger.error("New module creation failed: %s", e)
            return [APIEnhancement(
                gap_id=gap.gap_id, module_path=target_path,
                action="add_method",
                code_diff=f"Error: {e}",
                status="failed",
            )]

    async def _enhance_module(
        self, module_path: str, gaps: list, config: dict,
    ) -> list[APIEnhancement]:
        """Enhance a single module to fill its gaps."""
        src_path = Path(module_path)
        if not src_path.exists():
            return [
                APIEnhancement(
                    gap_id=g.gap_id, module_path=module_path,
                    action="add_method", code_diff=f"Module not found: {module_path}",
                    status="failed",
                )
                for g in gaps
            ]

        current_source = src_path.read_text()

        # Build gap descriptions for the LLM
        gap_descriptions = []
        for gap in gaps:
            gap_descriptions.append(
                f"- [{gap.gap_id}] {gap.gap_type.value}: {gap.description}\n"
                f"  Suggested: {gap.suggested_signature}\n"
                f"  Needed by tests: {gap.test_ids}\n"
                f"  Blocks requirements: {gap.req_ids}"
            )

        user_content = (
            f"## Module: {module_path}\n\n"
            f"## Current Source Code:\n```python\n{current_source}\n```\n\n"
            f"## Gaps to Fill:\n" + "\n".join(gap_descriptions) + "\n\n"
            f"Update the module to fill ALL gaps listed above. "
            f"Output the COMPLETE updated file."
        )

        try:
            enhanced_source = await self.llm_call(user_content=user_content)

            # Strip markdown fences if present
            if enhanced_source.startswith("```"):
                enhanced_source = enhanced_source.split("\n", 1)[1].rsplit("```", 1)[0]

            # Validate syntax
            ast.parse(enhanced_source)

            # Verify the enhanced source still has all original classes/functions
            original_names = self._extract_names(current_source)
            enhanced_names = self._extract_names(enhanced_source)
            missing = original_names - enhanced_names
            if missing:
                self.logger.warning(
                    "Enhancement removed existing names: %s. Rejecting.", missing
                )
                return [
                    APIEnhancement(
                        gap_id=g.gap_id, module_path=module_path,
                        action=g.gap_type.value.replace("missing_", "add_"),
                        code_diff=f"Enhancement would remove existing code: {missing}",
                        status="failed",
                    )
                    for g in gaps
                ]

            # Write the enhanced source
            src_path.write_text(enhanced_source)
            self.logger.info("Enhanced %s with %d gap fixes", module_path, len(gaps))

            return [
                APIEnhancement(
                    gap_id=g.gap_id,
                    module_path=module_path,
                    action=g.gap_type.value.replace("missing_", "add_"),
                    code_diff=f"Applied: {g.description}",
                    status="applied",
                )
                for g in gaps
            ]

        except SyntaxError as e:
            self.logger.warning("Enhanced code has syntax error: %s", e)
            return [
                APIEnhancement(
                    gap_id=g.gap_id, module_path=module_path,
                    action="modify_method",
                    code_diff=f"Syntax error in generated code: {e}",
                    status="failed",
                )
                for g in gaps
            ]
        except Exception as e:
            self.logger.error("Enhancement failed for %s: %s", module_path, e)
            return [
                APIEnhancement(
                    gap_id=g.gap_id, module_path=module_path,
                    action="modify_method",
                    code_diff=f"Error: {e}",
                    status="failed",
                )
                for g in gaps
            ]

    def _extract_names(self, source: str) -> set[str]:
        """Extract all top-level class and function names from source."""
        try:
            tree = ast.parse(source)
            names = set()
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    names.add(node.name)
            return names
        except SyntaxError:
            return set()

    def _regenerate_api_skills(self, config: dict) -> bool:
        """Regenerate API reference skills from the (now enhanced) source code."""
        try:
            from src.skills.generator import generate_all_api_skills
            skills_dir = config.get("skills", {}).get("skills_dir", "skills")
            api_dir = Path(skills_dir) / "api-reference"
            generate_all_api_skills("src/networking", str(api_dir))
            return True
        except Exception as e:
            self.logger.warning("Failed to regenerate API skills: %s", e)
            return False

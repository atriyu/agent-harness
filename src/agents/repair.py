"""Self-Healing Repair Agent: fixes test code bugs when tests fail due to code issues."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from src.agents.base import BaseAgent
from src.artifacts.models import (
    IndividualTestResult,
    RepairAttempt,
    RepairOutcome,
    TestRunResult,
    TestStatus,
)

SYSTEM_PROMPT = """\
You are a Python test automation debugging expert.

A generated test has failed due to a test code bug (not a product bug).
Given the test code and the error traceback, fix the test code.

Common issues to fix:
- Import errors (wrong module path)
- Assertion errors (wrong expected values or comparisons)
- Fixture errors (missing or misconfigured fixtures)
- Syntax issues

Output ONLY the corrected Python code for the entire test function.
Do not include markdown fences.
"""


class RepairAgent(BaseAgent):
    agent_name = "repair"
    default_task_type = "test_repair"

    async def run(self, inputs: Any) -> dict:
        store = inputs["store"]
        config = inputs["config"]

        repair_config = config.get("repair", {})
        if not repair_config.get("enabled", True):
            self.logger.info("Repair agent is disabled")
            return {"artifact_paths": [], "repairs": []}

        max_attempts = repair_config.get("max_attempts_per_test", 2)

        # Load the most recent test run result
        result_files = store.list_files("results", "run_*.json")
        if not result_files:
            return {"artifact_paths": [], "repairs": []}

        run_result = TestRunResult.model_validate_json(result_files[-1].read_text())

        # Find test-code failures (not product bugs)
        repairable = [
            t for t in run_result.test_results
            if t.status in (TestStatus.ERROR, TestStatus.FAILED)
            and t.traceback
            and self._is_test_bug(t)
        ]

        if not repairable:
            self.logger.info("No test code bugs to repair")
            return {"artifact_paths": [], "repairs": []}

        repairs: list[RepairAttempt] = []
        for test_result in repairable:
            for attempt in range(1, max_attempts + 1):
                repair = await self._attempt_repair(test_result, attempt, config)
                repairs.append(repair)
                if repair.outcome == RepairOutcome.FIXED:
                    break

        self.logger.info(
            "Repair: %d attempted, %d fixed",
            len(repairs),
            sum(1 for r in repairs if r.outcome == RepairOutcome.FIXED),
        )

        return {"artifact_paths": [], "repairs": repairs}

    def _is_test_bug(self, result: IndividualTestResult) -> bool:
        """Heuristic: classify whether a failure is a test code bug."""
        tb = (result.traceback or "").lower()
        test_bug_indicators = [
            "importerror", "modulenotfounderror", "syntaxerror",
            "attributeerror", "typeerror", "nameerror",
            "fixture", "conftest",
        ]
        return any(indicator in tb for indicator in test_bug_indicators)

    async def _attempt_repair(
        self, test_result: IndividualTestResult, attempt: int, config: dict,
    ) -> RepairAttempt:
        """Attempt to repair a single failing test."""
        # Try to find and read the test file
        test_code = self._read_test_code(test_result.test_id, config)

        user_content = (
            f"Test ID: {test_result.test_id}\n\n"
            f"Error traceback:\n{test_result.traceback}\n\n"
            f"Test code:\n{test_code}\n\n"
            f"Fix this test code."
        )

        try:
            fixed_code = await self.llm_call(
                user_content=user_content,
                system=SYSTEM_PROMPT,
            )

            # Validate the fix compiles
            if fixed_code.startswith("```"):
                fixed_code = fixed_code.split("\n", 1)[1].rsplit("```", 1)[0]

            ast.parse(fixed_code)

            # Write the fix back
            self._write_test_code(test_result.test_id, fixed_code, config)

            return RepairAttempt(
                test_id=test_result.test_id,
                attempt_number=attempt,
                original_error=test_result.traceback or "",
                patch_description="LLM-generated fix applied",
                outcome=RepairOutcome.FIXED,
            )

        except Exception as e:
            return RepairAttempt(
                test_id=test_result.test_id,
                attempt_number=attempt,
                original_error=test_result.traceback or "",
                patch_description=f"Repair failed: {e}",
                outcome=RepairOutcome.STILL_FAILING,
            )

    def _read_test_code(self, test_id: str, config: dict) -> str:
        """Read the source code for a test given its node ID."""
        # test_id format: test_code/test_file.py::test_func
        output_dir = Path(config["harness"]["output_dir"]) / "test_code"
        if "::" in test_id:
            file_part = test_id.split("::")[0]
            file_path = output_dir / Path(file_part).name
        else:
            file_path = output_dir / test_id

        if file_path.exists():
            return file_path.read_text()
        return f"# Could not locate test file for {test_id}"

    def _write_test_code(self, test_id: str, code: str, config: dict) -> None:
        """Write repaired code back to the test file."""
        output_dir = Path(config["harness"]["output_dir"]) / "test_code"
        if "::" in test_id:
            file_part = test_id.split("::")[0]
            file_path = output_dir / Path(file_part).name
        else:
            file_path = output_dir / test_id

        if file_path.exists():
            file_path.write_text(code)

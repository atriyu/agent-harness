"""Triage Agent: analyzes test failures, clusters them, and identifies root causes."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from src.agents.base import BaseAgent
from src.artifacts.models import (
    TestRunResult,
    TestStatus,
    TriageEntry,
    TriageReport,
)

class TriageAgent(BaseAgent):
    agent_name = "triage"
    default_task_type = "root_cause_analysis"
    core_system_prompt = """\
You are a QA triage engineer. Perform root cause analysis on test failures.

Group related failures into clusters. For each cluster determine:
- root_cause_category: one of "product_bug", "test_bug", "infra_issue", "config_error", "intermittent"
- severity: one of "critical", "high", "medium", "low"
- root_cause_description, evidence, recommended_action, confidence (0.0-1.0)
- affected_req_ids: which requirements are blocked

Output a JSON object:
{
  "entries": [
    {
      "failure_cluster_id": "FC-001",
      "affected_test_ids": ["test_id_1"],
      "affected_req_ids": ["REQ-VPN-001"],
      "root_cause_category": "product_bug",
      "severity": "high",
      "root_cause_description": "...",
      "evidence": ["error line 1"],
      "recommended_action": "...",
      "confidence": 0.85
    }
  ],
  "summary": "Executive-level summary with recommendation: ship/hold/investigate."
}

Output ONLY the JSON object.
"""

    async def run(self, inputs: Any) -> dict:
        store = inputs["store"]

        # Load the most recent test run result
        result_files = store.list_files("results", "run_*.json")
        if not result_files:
            self.logger.info("No test results to triage")
            return {"artifact_paths": []}

        run_result = TestRunResult.model_validate_json(result_files[-1].read_text())

        # Filter to failures only
        failures = [
            t for t in run_result.test_results
            if t.status in (TestStatus.FAILED, TestStatus.ERROR)
        ]

        if not failures:
            self.logger.info("No failures to triage -- all tests passed!")
            # Still generate a report with empty entries
            triage = TriageReport(
                run_id=run_result.run_id,
                generated_at=datetime.now(timezone.utc),
                total_failures=0,
                entries=[],
                summary="All tests passed. No failures to triage.",
            )
            path = store.save("triage", "triage_report.json", triage)
            return {"artifact_paths": [str(path)], "triage_report": triage}

        # Build failure summaries for the LLM
        failure_details = []
        for f in failures:
            failure_details.append(
                f"Test: {f.test_id}\n"
                f"Status: {f.status.value}\n"
                f"Traceback:\n{f.traceback or 'N/A'}\n"
                f"Stderr:\n{f.stderr[:500] if f.stderr else 'N/A'}\n"
            )

        user_content = (
            f"Test run {run_result.run_id}: {run_result.failed} failures, "
            f"{run_result.errored} errors out of {run_result.total} total.\n\n"
            f"Failures:\n\n" + "\n---\n".join(failure_details)
        )

        raw = await self.llm_call(
            user_content=user_content,
        )

        # Parse the triage response
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        triage_data = json.loads(text)

        entries = []
        for entry_data in triage_data.get("entries", []):
            entries.append(TriageEntry(
                failure_cluster_id=entry_data.get("failure_cluster_id", f"FC-{uuid.uuid4().hex[:4]}"),
                affected_test_ids=entry_data.get("affected_test_ids", []),
                affected_req_ids=entry_data.get("affected_req_ids", []),
                root_cause_category=entry_data["root_cause_category"],
                severity=entry_data.get("severity", "medium"),
                root_cause_description=entry_data["root_cause_description"],
                evidence=entry_data.get("evidence", []),
                recommended_action=entry_data.get("recommended_action", ""),
                confidence=entry_data.get("confidence", 0.5),
            ))

        triage = TriageReport(
            run_id=run_result.run_id,
            generated_at=datetime.now(timezone.utc),
            total_failures=len(failures),
            entries=entries,
            summary=triage_data.get("summary", ""),
        )

        path = store.save("triage", "triage_report.json", triage)
        self.logger.info(
            "Triage: %d failure clusters identified from %d failures",
            len(entries), len(failures),
        )

        return {"artifact_paths": [str(path)], "triage_report": triage}

"""Test Plan Generator Agent: designs comprehensive test plans from requirements.

This is the highest-value agent in the pipeline -- it uses Opus for maximum
reasoning quality since plan quality determines the quality of everything downstream.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from src.agents.base import BaseAgent
from src.artifacts.models import (
    RequirementSet,
    TestCaseSpec,
    TestPlan,
    TestStep,
    TestSuite,
)

class PlanAgent(BaseAgent):
    agent_name = "plan"
    default_task_type = "test_plan_generation"
    core_system_prompt = """\
You are an expert QA test architect. Design a comprehensive test plan covering every requirement.

For EACH requirement, generate test cases covering:
1. Happy path (valid inputs, expected configurations)
2. Negative tests (invalid inputs, error conditions)
3. Boundary conditions (limits, edge values)
4. Error recovery (restart, connection drop, exhaustion)
5. Cross-feature interactions where applicable

Output a JSON object with this structure:
{
  "suites": [
    {
      "suite_id": "TS-VPN-PROTO",
      "name": "VPN Protocol Tests",
      "category": "vpn",
      "test_cases": [
        {
          "test_id": "TC-VPN-PROTO-001",
          "traced_req_ids": ["REQ-VPN-001"],
          "category": "vpn",
          "title": "Verify WireGuard tunnel establishment",
          "description": "...",
          "preconditions": ["VPN gateway running", "Client configured"],
          "steps": [
            {"step_number": 1, "action": "Initiate WireGuard handshake", "expected": "Handshake completes within 5s"}
          ],
          "expected_result": "Tunnel established with encrypted traffic flow",
          "topology": "vpn_basic",
          "tools": ["scapy", "tcpdump"],
          "priority": "P0",
          "estimated_duration_seconds": 60,
          "tags": ["wireguard", "tunnel"]
        }
      ]
    }
  ]
}

Output ONLY the JSON object, no other text. Be thorough but practical.
"""

    async def run(self, inputs: Any) -> dict:
        store = inputs["store"]

        # Load requirement set
        req_set = store.load("requirements", "requirement_set.json", RequirementSet)

        # Build the prompt with all requirements
        req_summaries = []
        for req in req_set.requirements:
            req_summaries.append(
                f"- {req.req_id} [{req.category.value}] ({req.priority.value}): "
                f"{req.description}\n"
                f"  Acceptance: {'; '.join(req.acceptance_criteria)}"
            )

        user_content = (
            f"Requirements ({len(req_set.requirements)} total):\n\n"
            + "\n".join(req_summaries)
            + "\n\nDesign a comprehensive test plan covering all requirements."
        )

        raw = await self.llm_call(
            user_content=user_content,
        )

        # Parse the response
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        plan_data = json.loads(text)

        # Build the test plan
        suites = []
        total_cases = 0
        coverage_matrix: dict[str, list[str]] = {}

        for suite_data in plan_data.get("suites", []):
            test_cases = []
            for tc_data in suite_data.get("test_cases", []):
                # Parse steps
                steps = [TestStep(**s) for s in tc_data.get("steps", [])]
                tc = TestCaseSpec(
                    test_id=tc_data["test_id"],
                    traced_req_ids=tc_data.get("traced_req_ids", []),
                    category=tc_data.get("category", suite_data.get("category", "")),
                    title=tc_data["title"],
                    description=tc_data.get("description", ""),
                    preconditions=tc_data.get("preconditions", []),
                    steps=steps,
                    expected_result=tc_data.get("expected_result", ""),
                    topology=tc_data.get("topology", "full_stack"),
                    tools=tc_data.get("tools", []),
                    priority=tc_data.get("priority", "P2"),
                    estimated_duration_seconds=tc_data.get("estimated_duration_seconds", 60),
                    tags=tc_data.get("tags", []),
                )
                test_cases.append(tc)
                total_cases += 1

                # Update coverage matrix
                for req_id in tc.traced_req_ids:
                    coverage_matrix.setdefault(req_id, []).append(tc.test_id)

            suite = TestSuite(
                suite_id=suite_data.get("suite_id", f"TS-{uuid.uuid4().hex[:6]}"),
                name=suite_data.get("name", ""),
                category=suite_data.get("category", ""),
                test_cases=test_cases,
            )
            suites.append(suite)

        test_plan = TestPlan(
            plan_id=f"TP-{uuid.uuid4().hex[:8]}",
            version="1.0",
            generated_at=datetime.now(timezone.utc),
            source_requirement_set_version=req_set.version,
            suites=suites,
            total_test_cases=total_cases,
            coverage_matrix=coverage_matrix,
        )

        path = store.save("test_plans", "test_plan.json", test_plan)
        self.logger.info(
            "Generated test plan: %d suites, %d test cases",
            len(suites), total_cases,
        )

        return {"artifact_paths": [str(path)], "test_plan": test_plan}

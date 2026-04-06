"""Requirement Extraction Agent: extracts testable requirements from ingested documents."""

from __future__ import annotations

import json
from typing import Any
from datetime import datetime, timezone

from src.agents.base import BaseAgent
from src.artifacts.models import IngestedDocument, Requirement, RequirementSet

class ExtractAgent(BaseAgent):
    agent_name = "extract"
    default_task_type = "requirement_extraction"
    core_system_prompt = """\
You are a QA requirements analyst. Given a document section, extract ALL testable requirements.

Output a JSON array of requirement objects with these fields:
- req_id: string (format: REQ-{CATEGORY}-{NNN}, e.g. REQ-VPN-001)
- source_section: string (the section heading this was extracted from)
- category: string (one of: vpn, l4, l7, performance, security, ha)
- priority: string (P0, P1, P2, P3)
- description: string (clear, atomic, testable statement)
- acceptance_criteria: array of strings (specific, measurable conditions for pass/fail)
- tags: array of strings (keywords for filtering)

If a section contains no testable requirements, output an empty array: []

Output ONLY the JSON array, no other text.
"""

    async def run(self, inputs: Any) -> dict:
        store = inputs["store"]

        # Load ingested documents from the previous stage
        doc_files = store.list_files("requirements", "ingested_*.json")
        if not doc_files:
            raise ValueError("No ingested documents found")

        all_requirements: list[Requirement] = []
        source_doc_ids: list[str] = []
        counters: dict[str, int] = {}

        for doc_file in doc_files:
            doc = IngestedDocument.model_validate_json(doc_file.read_text())
            source_doc_ids.append(doc.doc_id)

            # Process each section
            for section in doc.sections:
                if not section.content.strip():
                    continue

                user_content = (
                    f"Document: {doc.title}\n"
                    f"Section: {section.heading}\n\n"
                    f"{section.content}"
                )

                try:
                    raw = await self.llm_call(
                        user_content=user_content,
                    )

                    # Parse the JSON response
                    text = raw.strip()
                    if text.startswith("```"):
                        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

                    reqs_data = json.loads(text)
                    if not isinstance(reqs_data, list):
                        reqs_data = [reqs_data]

                    for req_data in reqs_data:
                        # Ensure unique req_id with counter
                        cat = req_data.get("category", "vpn").upper()
                        counters[cat] = counters.get(cat, 0) + 1
                        req_data["req_id"] = f"REQ-{cat}-{counters[cat]:03d}"
                        req_data["source_doc_id"] = doc.doc_id
                        req_data["source_section"] = section.heading

                        req = Requirement.model_validate(req_data)
                        all_requirements.append(req)

                except Exception as e:
                    self.logger.warning(
                        "Failed to extract requirements from %s/%s: %s",
                        doc.title, section.heading, e,
                    )

        # Build coverage summary
        coverage: dict[str, int] = {}
        for req in all_requirements:
            coverage[req.category.value] = coverage.get(req.category.value, 0) + 1

        req_set = RequirementSet(
            version="1.0",
            generated_at=datetime.now(timezone.utc),
            source_documents=source_doc_ids,
            requirements=all_requirements,
            coverage_summary=coverage,
        )

        path = store.save("requirements", "requirement_set.json", req_set)
        self.logger.info(
            "Extracted %d requirements across %d categories",
            len(all_requirements), len(coverage),
        )

        return {"artifact_paths": [str(path)], "requirement_set": req_set}

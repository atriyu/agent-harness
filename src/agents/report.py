"""Report Generator Agent: produces HTML and markdown reports from pipeline outputs."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from src.agents.base import BaseAgent
from src.artifacts.models import (
    RequirementSet,
    TestPlan,
    TestRunResult,
    TriageReport,
)

SUMMARY_SYSTEM_PROMPT = """\
You are a QA report writer. Given test results and triage data, write a concise
executive summary (3-5 sentences) covering:
1. Overall pass rate and key metrics
2. Critical issues found
3. Recommendation (ship/hold/investigate)

Be direct and factual. No fluff.
"""


class ReportAgent(BaseAgent):
    agent_name = "report"
    default_task_type = "report_summary"

    async def run(self, inputs: Any) -> dict:
        store = inputs["store"]
        config = inputs["config"]
        output_dir = Path(config["harness"]["output_dir"])
        reports_dir = output_dir / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)

        # Load artifacts from previous stages
        req_set = self._load_optional(store, "requirements", "requirement_set.json", RequirementSet)
        test_plan = self._load_optional(store, "test_plans", "test_plan.json", TestPlan)

        # Load most recent results and triage
        result_files = store.list_files("results", "run_*.json")
        run_result = (
            TestRunResult.model_validate_json(result_files[-1].read_text())
            if result_files else None
        )

        triage_files = store.list_files("triage", "triage_report.json")
        triage = (
            TriageReport.model_validate_json(triage_files[0].read_text())
            if triage_files else None
        )

        # Generate executive summary via LLM
        executive_summary = await self._generate_summary(run_result, triage)

        # Build coverage matrix
        coverage = self._build_coverage(req_set, test_plan, run_result)

        # Render HTML report
        artifact_paths = []

        html_path = self._render_html(
            reports_dir, req_set, test_plan, run_result, triage,
            executive_summary, coverage,
        )
        artifact_paths.append(str(html_path))

        # Render markdown summary
        md_path = self._render_markdown(
            reports_dir, run_result, triage, executive_summary, coverage,
        )
        artifact_paths.append(str(md_path))

        self.logger.info("Reports generated: %s", [p.split("/")[-1] for p in artifact_paths])
        return {"artifact_paths": artifact_paths}

    def _load_optional(self, store, stage, filename, model):
        try:
            return store.load(stage, filename, model)
        except Exception:
            return None

    async def _generate_summary(
        self, run_result: TestRunResult | None, triage: TriageReport | None,
    ) -> str:
        if not run_result:
            return "No test results available."

        user_content = (
            f"Test results: {run_result.passed}/{run_result.total} passed "
            f"({run_result.failed} failed, {run_result.errored} errors)\n"
            f"Duration: {run_result.duration_seconds:.1f}s\n"
        )
        if triage and triage.entries:
            user_content += f"\nTriage findings:\n{triage.summary}\n"
            for e in triage.entries:
                user_content += (
                    f"- [{e.severity.value}] {e.root_cause_category.value}: "
                    f"{e.root_cause_description}\n"
                )

        return await self.llm_call(
            user_content=user_content,
            system=SUMMARY_SYSTEM_PROMPT,
        )

    def _build_coverage(self, req_set, test_plan, run_result) -> list[dict]:
        """Build a requirement coverage matrix."""
        if not req_set or not test_plan:
            return []

        coverage = []
        result_map = {}
        if run_result:
            for tr in run_result.test_results:
                result_map[tr.test_id] = tr.status.value

        for req in req_set.requirements:
            test_ids = test_plan.coverage_matrix.get(req.req_id, [])
            statuses = [result_map.get(tid, "not_run") for tid in test_ids]
            coverage.append({
                "req_id": req.req_id,
                "description": req.description[:80],
                "priority": req.priority.value,
                "test_count": len(test_ids),
                "passed": statuses.count("passed"),
                "failed": statuses.count("failed") + statuses.count("error"),
                "status": "pass" if all(s == "passed" for s in statuses) and statuses
                          else "fail" if any(s in ("failed", "error") for s in statuses)
                          else "no_tests",
            })
        return coverage

    def _render_html(
        self, reports_dir, req_set, test_plan, run_result, triage,
        executive_summary, coverage,
    ) -> Path:
        """Render the HTML report using Jinja2 template."""
        template_dir = Path(__file__).parent.parent / "reporting" / "templates"

        if (template_dir / "report.html.j2").exists():
            env = Environment(loader=FileSystemLoader(str(template_dir)))
            template = env.get_template("report.html.j2")
        else:
            # Inline fallback template
            from jinja2 import Template
            template = Template(FALLBACK_HTML_TEMPLATE)

        html = template.render(
            generated_at=datetime.now(timezone.utc).isoformat(),
            executive_summary=executive_summary,
            run_result=run_result,
            triage=triage,
            coverage=coverage,
            req_set=req_set,
            test_plan=test_plan,
        )

        path = reports_dir / "report.html"
        path.write_text(html)
        return path

    def _render_markdown(
        self, reports_dir, run_result, triage, executive_summary, coverage,
    ) -> Path:
        """Render a markdown summary."""
        lines = ["# QA Test Report\n"]
        lines.append(f"Generated: {datetime.now(timezone.utc).isoformat()}\n")

        lines.append("## Executive Summary\n")
        lines.append(executive_summary + "\n")

        if run_result:
            lines.append("## Results\n")
            lines.append(f"| Metric | Value |")
            lines.append(f"|--------|-------|")
            lines.append(f"| Total | {run_result.total} |")
            lines.append(f"| Passed | {run_result.passed} |")
            lines.append(f"| Failed | {run_result.failed} |")
            lines.append(f"| Errors | {run_result.errored} |")
            lines.append(f"| Duration | {run_result.duration_seconds:.1f}s |")
            lines.append("")

        if coverage:
            lines.append("## Requirement Coverage\n")
            lines.append("| Req ID | Priority | Tests | Status |")
            lines.append("|--------|----------|-------|--------|")
            for c in coverage:
                lines.append(
                    f"| {c['req_id']} | {c['priority']} | "
                    f"{c['passed']}/{c['test_count']} | {c['status']} |"
                )
            lines.append("")

        if triage and triage.entries:
            lines.append("## Failure Analysis\n")
            for e in triage.entries:
                lines.append(
                    f"### {e.failure_cluster_id} [{e.severity.value}]\n"
                    f"**Category**: {e.root_cause_category.value}\n"
                    f"**Description**: {e.root_cause_description}\n"
                    f"**Action**: {e.recommended_action}\n"
                    f"**Confidence**: {e.confidence:.0%}\n"
                )

        path = reports_dir / "summary.md"
        path.write_text("\n".join(lines))
        return path


FALLBACK_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head>
  <title>QA Test Report</title>
  <style>
    body { font-family: -apple-system, sans-serif; max-width: 960px; margin: 40px auto; padding: 0 20px; color: #333; }
    h1 { border-bottom: 2px solid #2563eb; padding-bottom: 8px; }
    .summary { background: #f0f9ff; border-left: 4px solid #2563eb; padding: 16px; margin: 16px 0; }
    .metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin: 16px 0; }
    .metric { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; text-align: center; }
    .metric .value { font-size: 2em; font-weight: bold; }
    .metric .label { color: #64748b; font-size: 0.9em; }
    .pass { color: #16a34a; }
    .fail { color: #dc2626; }
    table { width: 100%; border-collapse: collapse; margin: 16px 0; }
    th, td { padding: 8px 12px; text-align: left; border-bottom: 1px solid #e2e8f0; }
    th { background: #f8fafc; font-weight: 600; }
    .severity-critical { color: #dc2626; font-weight: bold; }
    .severity-high { color: #ea580c; }
    .severity-medium { color: #ca8a04; }
    .severity-low { color: #65a30d; }
  </style>
</head>
<body>
  <h1>QA Test Report</h1>
  <p><em>Generated: {{ generated_at }}</em></p>

  <div class="summary">
    <h2>Executive Summary</h2>
    <p>{{ executive_summary }}</p>
  </div>

  {% if run_result %}
  <h2>Test Results</h2>
  <div class="metrics">
    <div class="metric"><div class="value">{{ run_result.total }}</div><div class="label">Total</div></div>
    <div class="metric"><div class="value pass">{{ run_result.passed }}</div><div class="label">Passed</div></div>
    <div class="metric"><div class="value fail">{{ run_result.failed }}</div><div class="label">Failed</div></div>
    <div class="metric"><div class="value">{{ run_result.errored }}</div><div class="label">Errors</div></div>
    <div class="metric"><div class="value">{{ "%.1f"|format(run_result.duration_seconds) }}s</div><div class="label">Duration</div></div>
  </div>
  {% endif %}

  {% if coverage %}
  <h2>Requirement Coverage</h2>
  <table>
    <tr><th>Req ID</th><th>Priority</th><th>Tests</th><th>Passed</th><th>Status</th></tr>
    {% for c in coverage %}
    <tr>
      <td>{{ c.req_id }}</td>
      <td>{{ c.priority }}</td>
      <td>{{ c.test_count }}</td>
      <td>{{ c.passed }}</td>
      <td class="{{ 'pass' if c.status == 'pass' else 'fail' }}">{{ c.status }}</td>
    </tr>
    {% endfor %}
  </table>
  {% endif %}

  {% if triage and triage.entries %}
  <h2>Failure Analysis</h2>
  {% for e in triage.entries %}
  <div style="margin: 16px 0; padding: 12px; border: 1px solid #e2e8f0; border-radius: 8px;">
    <h3>{{ e.failure_cluster_id }}
      <span class="severity-{{ e.severity.value }}">{{ e.severity.value }}</span>
    </h3>
    <p><strong>Category:</strong> {{ e.root_cause_category.value }}</p>
    <p><strong>Root Cause:</strong> {{ e.root_cause_description }}</p>
    <p><strong>Action:</strong> {{ e.recommended_action }}</p>
    <p><strong>Confidence:</strong> {{ "%.0f"|format(e.confidence * 100) }}%</p>
    <p><strong>Affected Tests:</strong> {{ e.affected_test_ids | join(", ") }}</p>
  </div>
  {% endfor %}
  {% endif %}
</body>
</html>
"""

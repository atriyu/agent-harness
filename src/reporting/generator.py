"""Report generation utilities: coverage matrix, metrics computation, chart data."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.artifacts.models import (
    RequirementSet,
    TestPlan,
    TestRunResult,
    TestStatus,
    TriageReport,
)


@dataclass
class CoverageEntry:
    req_id: str
    description: str
    category: str
    priority: str
    test_ids: list[str] = field(default_factory=list)
    test_count: int = 0
    passed: int = 0
    failed: int = 0
    errored: int = 0
    skipped: int = 0
    not_run: int = 0
    status: str = "no_tests"  # "pass", "fail", "partial", "no_tests"


@dataclass
class CategorySummary:
    category: str
    total_tests: int = 0
    passed: int = 0
    failed: int = 0
    errored: int = 0
    pass_rate: float = 0.0


@dataclass
class ReportData:
    """All computed data needed to render a report."""
    generated_at: str = ""
    run_result: TestRunResult | None = None
    triage: TriageReport | None = None
    coverage: list[CoverageEntry] = field(default_factory=list)
    category_summaries: list[CategorySummary] = field(default_factory=list)
    pass_rate: float = 0.0
    critical_issues: int = 0
    high_issues: int = 0
    blocked_requirements: list[str] = field(default_factory=list)


def build_coverage_matrix(
    req_set: RequirementSet | None,
    test_plan: TestPlan | None,
    run_result: TestRunResult | None,
) -> list[CoverageEntry]:
    """Build a requirement-to-test coverage matrix with pass/fail status."""
    if not req_set or not test_plan:
        return []

    # Build result map from node IDs
    result_map: dict[str, TestStatus] = {}
    if run_result:
        for tr in run_result.test_results:
            result_map[tr.test_id] = tr.status
            # Also map by short test_id (without file prefix)
            if "::" in tr.test_id:
                short = tr.test_id.split("::")[-1]
                result_map[short] = tr.status

    coverage = []
    for req in req_set.requirements:
        test_ids = test_plan.coverage_matrix.get(req.req_id, [])

        entry = CoverageEntry(
            req_id=req.req_id,
            description=req.description[:100],
            category=req.category.value,
            priority=req.priority.value,
            test_ids=test_ids,
            test_count=len(test_ids),
        )

        for tid in test_ids:
            status = result_map.get(tid)
            if status == TestStatus.PASSED:
                entry.passed += 1
            elif status == TestStatus.FAILED:
                entry.failed += 1
            elif status == TestStatus.ERROR:
                entry.errored += 1
            elif status == TestStatus.SKIPPED:
                entry.skipped += 1
            else:
                entry.not_run += 1

        # Determine overall status
        if not test_ids:
            entry.status = "no_tests"
        elif entry.failed + entry.errored > 0:
            entry.status = "fail"
        elif entry.passed == entry.test_count:
            entry.status = "pass"
        elif entry.passed > 0:
            entry.status = "partial"
        else:
            entry.status = "no_tests"

        coverage.append(entry)

    return coverage


def build_category_summaries(run_result: TestRunResult | None) -> list[CategorySummary]:
    """Summarize test results by category (extracted from test IDs/markers)."""
    if not run_result:
        return []

    categories: dict[str, CategorySummary] = {}

    for tr in run_result.test_results:
        # Infer category from test_id or node_id
        cat = _infer_category(tr.test_id)
        if cat not in categories:
            categories[cat] = CategorySummary(category=cat)

        summary = categories[cat]
        summary.total_tests += 1
        if tr.status == TestStatus.PASSED:
            summary.passed += 1
        elif tr.status == TestStatus.FAILED:
            summary.failed += 1
        elif tr.status == TestStatus.ERROR:
            summary.errored += 1

    for summary in categories.values():
        if summary.total_tests > 0:
            summary.pass_rate = summary.passed / summary.total_tests * 100

    return sorted(categories.values(), key=lambda s: s.category)


def _infer_category(test_id: str) -> str:
    """Infer test category from the test ID or file path."""
    lower = test_id.lower()
    for cat in ["vpn", "l4", "l7", "performance", "security", "ha"]:
        if cat in lower:
            return cat
    return "other"


def build_report_data(
    req_set: RequirementSet | None,
    test_plan: TestPlan | None,
    run_result: TestRunResult | None,
    triage: TriageReport | None,
) -> ReportData:
    """Assemble all computed report data."""
    coverage = build_coverage_matrix(req_set, test_plan, run_result)
    category_summaries = build_category_summaries(run_result)

    pass_rate = 0.0
    if run_result and run_result.total > 0:
        pass_rate = run_result.passed / run_result.total * 100

    critical_issues = 0
    high_issues = 0
    blocked_reqs: set[str] = set()

    if triage:
        for entry in triage.entries:
            if entry.severity.value == "critical":
                critical_issues += 1
            elif entry.severity.value == "high":
                high_issues += 1
            blocked_reqs.update(entry.affected_req_ids)

    return ReportData(
        generated_at=datetime.now(timezone.utc).isoformat(),
        run_result=run_result,
        triage=triage,
        coverage=coverage,
        category_summaries=category_summaries,
        pass_rate=pass_rate,
        critical_issues=critical_issues,
        high_issues=high_issues,
        blocked_requirements=sorted(blocked_reqs),
    )

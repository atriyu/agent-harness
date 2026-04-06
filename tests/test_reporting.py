"""Tests for the report generator utilities."""

from datetime import datetime, timezone

from src.artifacts.models import (
    Category,
    IndividualTestResult,
    Priority,
    Requirement,
    RequirementSet,
    TestCaseSpec,
    TestPlan,
    TestRunResult,
    TestStatus,
    TestStep,
    TestSuite,
    TriageEntry,
    TriageReport,
    RootCauseCategory,
    Severity,
)
from src.reporting.generator import (
    build_category_summaries,
    build_coverage_matrix,
    build_report_data,
    _infer_category,
)


def _make_req_set():
    return RequirementSet(
        version="1.0",
        generated_at=datetime.now(timezone.utc),
        source_documents=["doc1"],
        requirements=[
            Requirement(
                req_id="REQ-VPN-001", source_doc_id="doc1", source_section="VPN",
                category=Category.VPN, priority=Priority.P0,
                description="WireGuard support", acceptance_criteria=["Tunnel up in 5s"],
            ),
            Requirement(
                req_id="REQ-L4-001", source_doc_id="doc1", source_section="L4",
                category=Category.L4, priority=Priority.P1,
                description="TCP load balancing", acceptance_criteria=["Even distribution"],
            ),
        ],
    )


def _make_test_plan():
    return TestPlan(
        plan_id="TP-001", version="1.0",
        generated_at=datetime.now(timezone.utc),
        source_requirement_set_version="1.0",
        suites=[
            TestSuite(
                suite_id="TS-VPN", name="VPN Tests", category="vpn",
                test_cases=[
                    TestCaseSpec(
                        test_id="TC-VPN-001", traced_req_ids=["REQ-VPN-001"],
                        category="vpn", title="WireGuard tunnel test",
                        description="", steps=[TestStep(step_number=1, action="Connect", expected="Up")],
                        expected_result="Tunnel up", topology="vpn_basic", priority=Priority.P0,
                    ),
                ],
            ),
        ],
        total_test_cases=1,
        coverage_matrix={"REQ-VPN-001": ["TC-VPN-001"]},
    )


def _make_run_result():
    return TestRunResult(
        run_id="run1", timestamp=datetime.now(timezone.utc),
        topology_used="vpn_basic", total=2, passed=1, failed=1, errored=0, skipped=0,
        duration_seconds=10.0,
        test_results=[
            IndividualTestResult(test_id="TC-VPN-001", status=TestStatus.PASSED, duration_seconds=5.0),
            IndividualTestResult(test_id="TC-L4-001", status=TestStatus.FAILED, duration_seconds=5.0, traceback="AssertionError"),
        ],
    )


def test_infer_category():
    assert _infer_category("test_vpn_tunnel") == "vpn"
    assert _infer_category("test_l4_tcp_lb") == "l4"
    assert _infer_category("test_l7_proxy_routing") == "l7"
    assert _infer_category("test_something") == "other"


def test_build_coverage_matrix():
    coverage = build_coverage_matrix(_make_req_set(), _make_test_plan(), _make_run_result())
    assert len(coverage) == 2

    vpn_entry = [c for c in coverage if c.req_id == "REQ-VPN-001"][0]
    assert vpn_entry.test_count == 1
    assert vpn_entry.passed == 1
    assert vpn_entry.status == "pass"

    l4_entry = [c for c in coverage if c.req_id == "REQ-L4-001"][0]
    assert l4_entry.test_count == 0
    assert l4_entry.status == "no_tests"


def test_build_category_summaries():
    summaries = build_category_summaries(_make_run_result())
    assert len(summaries) >= 1

    vpn_summary = [s for s in summaries if s.category == "vpn"]
    assert len(vpn_summary) == 1
    assert vpn_summary[0].passed == 1


def test_build_report_data():
    data = build_report_data(
        _make_req_set(), _make_test_plan(), _make_run_result(), None,
    )
    assert data.pass_rate == 50.0
    assert data.generated_at
    assert len(data.coverage) == 2


def test_build_report_data_with_triage():
    triage = TriageReport(
        run_id="run1", generated_at=datetime.now(timezone.utc),
        total_failures=1,
        entries=[
            TriageEntry(
                failure_cluster_id="FC-001", affected_test_ids=["TC-L4-001"],
                affected_req_ids=["REQ-L4-001"],
                root_cause_category=RootCauseCategory.PRODUCT_BUG,
                severity=Severity.CRITICAL,
                root_cause_description="LB not distributing",
                evidence=["All traffic to backend1"],
                recommended_action="File bug",
                confidence=0.9,
            ),
        ],
        summary="1 critical product bug found",
    )

    data = build_report_data(_make_req_set(), _make_test_plan(), _make_run_result(), triage)
    assert data.critical_issues == 1
    assert "REQ-L4-001" in data.blocked_requirements

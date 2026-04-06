"""Tests for artifact models and store."""

from datetime import datetime, timezone

from src.artifacts.models import (
    Category,
    DocumentSection,
    IngestedDocument,
    Priority,
    Requirement,
    RequirementSet,
    TestCaseSpec,
    TestPlan,
    TestStep,
    TestSuite,
    PipelineStage,
    PipelineState,
    StageResult,
)
from src.artifacts.store import ArtifactStore


def test_requirement_roundtrip():
    req = Requirement(
        req_id="REQ-VPN-001",
        source_doc_id="abc123",
        source_section="VPN Requirements",
        category=Category.VPN,
        priority=Priority.P0,
        description="Support WireGuard protocol",
        acceptance_criteria=["Tunnel establishes within 5s"],
        tags=["wireguard"],
    )
    json_str = req.model_dump_json()
    loaded = Requirement.model_validate_json(json_str)
    assert loaded.req_id == "REQ-VPN-001"
    assert loaded.category == Category.VPN


def test_test_plan_structure():
    step = TestStep(step_number=1, action="Connect VPN", expected="Tunnel up")
    tc = TestCaseSpec(
        test_id="TC-VPN-001",
        traced_req_ids=["REQ-VPN-001"],
        category="vpn",
        title="Test WireGuard tunnel",
        description="Verify tunnel establishment",
        steps=[step],
        expected_result="Tunnel established",
        topology="vpn_basic",
        priority=Priority.P0,
    )
    suite = TestSuite(
        suite_id="TS-VPN",
        name="VPN Tests",
        category="vpn",
        test_cases=[tc],
    )
    plan = TestPlan(
        plan_id="TP-001",
        version="1.0",
        generated_at=datetime.now(timezone.utc),
        source_requirement_set_version="1.0",
        suites=[suite],
        total_test_cases=1,
        coverage_matrix={"REQ-VPN-001": ["TC-VPN-001"]},
    )
    assert plan.total_test_cases == 1
    assert len(plan.suites) == 1
    assert plan.suites[0].test_cases[0].test_id == "TC-VPN-001"


def test_pipeline_state():
    state = PipelineState(
        run_id="test123",
        started_at=datetime.now(timezone.utc),
        current_stage=PipelineStage.INGEST,
    )
    state.completed_stages["ingest"] = StageResult(status="success", artifact_paths=["a.json"])
    json_str = state.model_dump_json()
    loaded = PipelineState.model_validate_json(json_str)
    assert loaded.run_id == "test123"
    assert "ingest" in loaded.completed_stages


def test_artifact_store(tmp_output_dir):
    store = ArtifactStore(tmp_output_dir)

    req = Requirement(
        req_id="REQ-L4-001",
        source_doc_id="doc1",
        source_section="L4 Requirements",
        category=Category.L4,
        priority=Priority.P1,
        description="TCP load balancing",
        acceptance_criteria=["Even distribution"],
    )

    path = store.save("requirements", "test_req.json", req)
    assert path.exists()

    loaded = store.load("requirements", "test_req.json", Requirement)
    assert loaded.req_id == "REQ-L4-001"


def test_artifact_store_text(tmp_output_dir):
    store = ArtifactStore(tmp_output_dir)
    store.save_text("test_stage", "hello.txt", "Hello World")
    assert store.load_text("test_stage", "hello.txt") == "Hello World"
    assert store.exists("test_stage", "hello.txt")
    assert not store.exists("test_stage", "nonexistent.txt")

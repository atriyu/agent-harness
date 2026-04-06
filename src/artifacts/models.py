"""Pydantic models defining the contract between all pipeline agents.

Every inter-agent artifact is defined here so that producers and consumers
share a single source of truth for schema validation.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Category(str, Enum):
    VPN = "vpn"
    L4 = "l4"
    L7 = "l7"
    PERFORMANCE = "performance"
    SECURITY = "security"
    HA = "ha"


class Priority(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class TestStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"


class RootCauseCategory(str, Enum):
    PRODUCT_BUG = "product_bug"
    TEST_BUG = "test_bug"
    INFRA_ISSUE = "infra_issue"
    CONFIG_ERROR = "config_error"
    INTERMITTENT = "intermittent"


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RepairOutcome(str, Enum):
    FIXED = "fixed"
    STILL_FAILING = "still_failing"
    NEW_ERROR = "new_error"


# ---------------------------------------------------------------------------
# Stage 1: Document Ingestion
# ---------------------------------------------------------------------------

class DocumentSection(BaseModel):
    section_id: str
    heading: str
    content: str  # Markdown
    level: int = Field(ge=1, le=6)


class IngestedDocument(BaseModel):
    doc_id: str  # SHA256 of original content
    source_path: str
    source_format: Literal["pdf", "markdown", "html"]
    title: str
    sections: list[DocumentSection]
    metadata: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Stage 2: Requirement Extraction
# ---------------------------------------------------------------------------

class Requirement(BaseModel):
    req_id: str  # e.g. REQ-VPN-001
    source_doc_id: str
    source_section: str
    category: Category
    priority: Priority
    description: str
    acceptance_criteria: list[str]
    tags: list[str] = Field(default_factory=list)


class RequirementSet(BaseModel):
    version: str
    generated_at: datetime
    source_documents: list[str]  # doc_ids
    requirements: list[Requirement]
    coverage_summary: dict[str, int] = Field(default_factory=dict)  # category -> count


# ---------------------------------------------------------------------------
# Stage 3: Test Plan
# ---------------------------------------------------------------------------

class TestStep(BaseModel):
    step_number: int
    action: str
    expected: str


class TestCaseSpec(BaseModel):
    test_id: str  # e.g. TC-VPN-PROTO-001
    traced_req_ids: list[str]
    category: str
    title: str
    description: str
    preconditions: list[str] = Field(default_factory=list)
    steps: list[TestStep]
    expected_result: str
    topology: str  # Topology name from config
    tools: list[str] = Field(default_factory=list)
    priority: Priority
    estimated_duration_seconds: int = 60
    tags: list[str] = Field(default_factory=list)


class TestSuite(BaseModel):
    suite_id: str
    name: str
    category: str
    test_cases: list[TestCaseSpec]


class TestPlan(BaseModel):
    plan_id: str
    version: str
    generated_at: datetime
    source_requirement_set_version: str
    suites: list[TestSuite]
    total_test_cases: int = 0
    coverage_matrix: dict[str, list[str]] = Field(default_factory=dict)  # req_id -> [test_ids]


# ---------------------------------------------------------------------------
# Stage 5: Test Execution Results
# ---------------------------------------------------------------------------

class IndividualTestResult(BaseModel):
    test_id: str
    status: TestStatus
    duration_seconds: float = 0.0
    stdout: str = ""
    stderr: str = ""
    traceback: str | None = None
    artifacts: dict[str, str] = Field(default_factory=dict)  # name -> path


class RepairAttempt(BaseModel):
    test_id: str
    attempt_number: int
    original_error: str
    patch_description: str
    outcome: RepairOutcome


class TestRunResult(BaseModel):
    run_id: str
    timestamp: datetime
    topology_used: str
    total: int
    passed: int
    failed: int
    errored: int
    skipped: int
    duration_seconds: float
    test_results: list[IndividualTestResult]
    repair_attempts: list[RepairAttempt] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Stage 7: Triage
# ---------------------------------------------------------------------------

class TriageEntry(BaseModel):
    failure_cluster_id: str
    affected_test_ids: list[str]
    affected_req_ids: list[str]
    root_cause_category: RootCauseCategory
    severity: Severity
    root_cause_description: str
    evidence: list[str]
    recommended_action: str
    confidence: float = Field(ge=0.0, le=1.0)


class TriageReport(BaseModel):
    run_id: str
    generated_at: datetime
    total_failures: int
    entries: list[TriageEntry]
    summary: str  # LLM-generated natural language summary


# ---------------------------------------------------------------------------
# Stage 3b: Gap Analysis
# ---------------------------------------------------------------------------

class GapType(str, Enum):
    MISSING_METHOD = "missing_method"
    MISSING_PARAMETER = "missing_parameter"
    MISSING_RETURN_FIELD = "missing_return_field"
    MISSING_TOOL = "missing_tool"          # CLI tool not wrapped by any module
    MISSING_MODULE = "missing_module"      # Entirely new helper module needed


class APIGap(BaseModel):
    gap_id: str
    severity: Literal["critical", "minor"]
    test_ids: list[str] = Field(default_factory=list)
    req_ids: list[str] = Field(default_factory=list)
    module: str = ""  # Existing module path, or empty for new modules
    gap_type: GapType
    description: str
    suggested_signature: str = ""
    tool_name: str = ""              # CLI tool needed (e.g., "wget", "ab", "wrk")
    suggested_module: str = ""       # Suggested new module path for MISSING_MODULE/TOOL


class GapReport(BaseModel):
    plan_id: str
    gaps: list[APIGap]
    total_critical: int = 0
    total_minor: int = 0
    all_resolvable: bool = True


# ---------------------------------------------------------------------------
# Stage 3c: API Enhancement
# ---------------------------------------------------------------------------

class APIEnhancement(BaseModel):
    gap_id: str
    module_path: str
    action: Literal["add_method", "add_parameter", "modify_method"]
    code_diff: str  # Description of what changed
    status: Literal["applied", "failed", "skipped"]


class EnhancementReport(BaseModel):
    gap_report_id: str
    enhancements: list[APIEnhancement]
    total_applied: int = 0
    total_failed: int = 0
    api_skills_regenerated: bool = False


# ---------------------------------------------------------------------------
# Pipeline State
# ---------------------------------------------------------------------------

class PipelineStage(str, Enum):
    INGEST = "ingest"
    EXTRACT = "extract"
    PLAN = "plan"
    GAP_ANALYSIS = "gap_analysis"
    API_ENHANCE = "api_enhance"
    CODEGEN = "codegen"
    EXECUTE = "execute"
    REPAIR = "repair"
    TRIAGE = "triage"
    REPORT = "report"
    COMPLETE = "complete"


class StageResult(BaseModel):
    status: Literal["success", "failed", "skipped"]
    artifact_paths: list[str] = Field(default_factory=list)
    error: str | None = None
    duration_seconds: float = 0.0


class PipelineState(BaseModel):
    run_id: str
    started_at: datetime
    current_stage: PipelineStage = PipelineStage.INGEST
    completed_stages: dict[str, StageResult] = Field(default_factory=dict)
    config_path: str = ""
    error: str | None = None

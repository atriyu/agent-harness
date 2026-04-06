"""Pipeline state machine with checkpoint/resume support."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from src.artifacts.models import PipelineStage, PipelineState, StageResult


# The ordered stages the pipeline executes (repair is handled within execute)
STAGE_ORDER: list[PipelineStage] = [
    PipelineStage.INGEST,
    PipelineStage.EXTRACT,
    PipelineStage.PLAN,
    PipelineStage.GAP_ANALYSIS,
    PipelineStage.API_ENHANCE,
    PipelineStage.CODEGEN,
    PipelineStage.EXECUTE,
    # REPAIR is triggered conditionally inside EXECUTE
    PipelineStage.TRIAGE,
    PipelineStage.REPORT,
]


def new_pipeline_state(config_path: str = "") -> PipelineState:
    """Create a fresh pipeline state for a new run."""
    return PipelineState(
        run_id=uuid.uuid4().hex[:12],
        started_at=datetime.now(timezone.utc),
        current_stage=PipelineStage.INGEST,
        config_path=config_path,
    )


def load_pipeline_state(output_dir: Path) -> PipelineState:
    """Resume a pipeline from a checkpoint file."""
    state_file = output_dir / "pipeline_state.json"
    if not state_file.exists():
        raise FileNotFoundError(f"No checkpoint found at {state_file}")
    return PipelineState.model_validate_json(state_file.read_text())


def save_pipeline_state(state: PipelineState, output_dir: Path) -> Path:
    """Persist the pipeline state to disk."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "pipeline_state.json"
    path.write_text(state.model_dump_json(indent=2))
    return path


def is_stage_completed(state: PipelineState, stage: PipelineStage) -> bool:
    """Check if a stage has already been completed (for resume)."""
    return stage.value in state.completed_stages


def mark_stage_completed(
    state: PipelineState,
    stage: PipelineStage,
    artifact_paths: list[str] | None = None,
    duration: float = 0.0,
) -> PipelineState:
    """Mark a stage as successfully completed."""
    state.completed_stages[stage.value] = StageResult(
        status="success",
        artifact_paths=artifact_paths or [],
        duration_seconds=duration,
    )
    return state


def mark_stage_failed(
    state: PipelineState,
    stage: PipelineStage,
    error: str,
    duration: float = 0.0,
) -> PipelineState:
    """Mark a stage as failed."""
    state.completed_stages[stage.value] = StageResult(
        status="failed",
        error=error,
        duration_seconds=duration,
    )
    state.error = error
    return state

"""Tests for the orchestrator state machine and pipeline."""

from datetime import datetime, timezone
from pathlib import Path

from src.artifacts.models import PipelineStage, PipelineState, StageResult
from src.orchestrator.state import (
    STAGE_ORDER,
    is_stage_completed,
    load_pipeline_state,
    mark_stage_completed,
    mark_stage_failed,
    new_pipeline_state,
    save_pipeline_state,
)


def test_new_pipeline_state():
    state = new_pipeline_state("config/harness.yaml")
    assert state.run_id
    assert len(state.run_id) == 12
    assert state.current_stage == PipelineStage.INGEST
    assert state.config_path == "config/harness.yaml"
    assert not state.error


def test_stage_order():
    assert STAGE_ORDER[0] == PipelineStage.INGEST
    assert STAGE_ORDER[-1] == PipelineStage.REPORT
    assert PipelineStage.EXTRACT in STAGE_ORDER


def test_mark_stage_completed():
    state = new_pipeline_state()
    mark_stage_completed(state, PipelineStage.INGEST, ["a.json"], 1.5)

    assert is_stage_completed(state, PipelineStage.INGEST)
    assert not is_stage_completed(state, PipelineStage.EXTRACT)

    result = state.completed_stages["ingest"]
    assert result.status == "success"
    assert result.artifact_paths == ["a.json"]
    assert result.duration_seconds == 1.5


def test_mark_stage_failed():
    state = new_pipeline_state()
    mark_stage_failed(state, PipelineStage.EXTRACT, "LLM error", 2.0)

    assert is_stage_completed(state, PipelineStage.EXTRACT)
    result = state.completed_stages["extract"]
    assert result.status == "failed"
    assert result.error == "LLM error"
    assert state.error == "LLM error"


def test_checkpoint_roundtrip(tmp_path):
    state = new_pipeline_state("test.yaml")
    mark_stage_completed(state, PipelineStage.INGEST, ["doc.json"])
    mark_stage_completed(state, PipelineStage.EXTRACT, ["reqs.json"])

    save_pipeline_state(state, tmp_path)
    loaded = load_pipeline_state(tmp_path)

    assert loaded.run_id == state.run_id
    assert is_stage_completed(loaded, PipelineStage.INGEST)
    assert is_stage_completed(loaded, PipelineStage.EXTRACT)
    assert not is_stage_completed(loaded, PipelineStage.PLAN)


def test_load_nonexistent_checkpoint(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError):
        load_pipeline_state(tmp_path / "nonexistent")

"""Filesystem-backed artifact persistence.

Each pipeline stage writes its output artifacts as JSON files under the
run's output directory. The store handles serialization, loading, and
path management.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel


class ArtifactStore:
    """Manages reading and writing pipeline artifacts to the filesystem."""

    def __init__(self, output_dir: str | Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _stage_dir(self, stage: str) -> Path:
        d = self.output_dir / stage
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save(self, stage: str, filename: str, artifact: BaseModel) -> Path:
        """Save a Pydantic model as a JSON file under the stage directory.

        Returns the path to the written file.
        """
        stage_dir = self._stage_dir(stage)
        path = stage_dir / filename
        path.write_text(artifact.model_dump_json(indent=2))
        return path

    def save_text(self, stage: str, filename: str, content: str) -> Path:
        """Save raw text content under the stage directory."""
        stage_dir = self._stage_dir(stage)
        path = stage_dir / filename
        path.write_text(content)
        return path

    def load(self, stage: str, filename: str, model: type[BaseModel]) -> BaseModel:
        """Load a JSON artifact and validate it as the given Pydantic model."""
        path = self._stage_dir(stage) / filename
        return model.model_validate_json(path.read_text())

    def load_text(self, stage: str, filename: str) -> str:
        """Load raw text content from a stage directory."""
        path = self._stage_dir(stage) / filename
        return path.read_text()

    def list_files(self, stage: str, pattern: str = "*.json") -> list[Path]:
        """List all files matching a pattern in a stage directory."""
        return sorted(self._stage_dir(stage).glob(pattern))

    def exists(self, stage: str, filename: str) -> bool:
        return (self._stage_dir(stage) / filename).exists()

    def save_state(self, state: BaseModel) -> Path:
        """Save pipeline state to the root output directory."""
        path = self.output_dir / "pipeline_state.json"
        path.write_text(state.model_dump_json(indent=2))
        return path

    def load_state(self, model: type[BaseModel]) -> BaseModel:
        """Load pipeline state from the root output directory."""
        path = self.output_dir / "pipeline_state.json"
        return model.model_validate_json(path.read_text())

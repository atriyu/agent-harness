"""Schema validation helpers for artifacts."""

from __future__ import annotations

from pydantic import BaseModel, ValidationError


def validate_artifact(data: str | dict, model: type[BaseModel]) -> tuple[BaseModel | None, str | None]:
    """Attempt to validate data against a Pydantic model.

    Returns (instance, None) on success or (None, error_message) on failure.
    """
    try:
        if isinstance(data, str):
            return model.model_validate_json(data), None
        return model.model_validate(data), None
    except ValidationError as e:
        return None, str(e)

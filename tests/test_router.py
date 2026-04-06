"""Tests for model router and token tracker."""

import pytest
from unittest.mock import AsyncMock

from pydantic import BaseModel

from src.router.model_router import (
    AnthropicProvider,
    CascadeExhaustedError,
    LLMProvider,
    LLMResponse,
    ModelRouter,
)
from src.router.token_tracker import TokenTracker, UsageRecord


class MockProvider(LLMProvider):
    """Mock LLM provider for testing."""

    def __init__(self, responses: list[str] | None = None):
        self._responses = responses or ['{"name": "test"}']
        self._call_count = 0

    async def call(self, model_id, system, messages, max_tokens):
        idx = min(self._call_count, len(self._responses) - 1)
        self._call_count += 1
        return LLMResponse(
            text=self._responses[idx],
            input_tokens=100,
            output_tokens=50,
            model_id=model_id,
        )


def make_router(provider=None, tracker=None, routing=None):
    config = {
        "tiers": {
            "haiku": {"id": "haiku-test", "max_tokens": 1024},
            "sonnet": {"id": "sonnet-test", "max_tokens": 2048},
            "opus": {"id": "opus-test", "max_tokens": 4096},
        },
        "routing": routing or {"test_task": "haiku", "complex_task": "opus"},
        "cascade_on_validation_failure": True,
        "max_cascade_depth": 2,
    }
    return ModelRouter(
        config=config,
        provider=provider or MockProvider(),
        tracker=tracker or TokenTracker(max_cost_usd=100),
    )


@pytest.mark.asyncio
async def test_basic_routing():
    provider = MockProvider(["Hello from LLM"])
    router = make_router(provider=provider)
    result = await router.call("test_task", "system", [{"role": "user", "content": "hi"}])
    assert result == "Hello from LLM"
    assert provider._call_count == 1


@pytest.mark.asyncio
async def test_routing_with_response_model():
    class TestModel(BaseModel):
        name: str

    provider = MockProvider(['{"name": "test_value"}'])
    router = make_router(provider=provider)
    result = await router.call(
        "test_task", "system",
        [{"role": "user", "content": "hi"}],
        response_model=TestModel,
    )
    assert isinstance(result, TestModel)
    assert result.name == "test_value"


@pytest.mark.asyncio
async def test_cascade_on_validation_failure():
    class TestModel(BaseModel):
        name: str
        value: int

    # First response invalid, second valid
    provider = MockProvider([
        '{"name": "test"}',           # Missing 'value' field
        '{"name": "test", "value": 42}',  # Valid
    ])
    router = make_router(provider=provider)
    result = await router.call(
        "test_task", "system",
        [{"role": "user", "content": "hi"}],
        response_model=TestModel,
    )
    assert result.value == 42
    assert provider._call_count == 2  # Cascaded from haiku to sonnet


@pytest.mark.asyncio
async def test_unknown_task_type():
    router = make_router()
    with pytest.raises(ValueError, match="Unknown task type"):
        await router.call("nonexistent", "system", [{"role": "user", "content": "hi"}])


def test_token_tracker_recording():
    tracker = TokenTracker(max_cost_usd=100)
    tracker.record(UsageRecord(
        task_type="test", tier="haiku", model_id="h",
        input_tokens=1000, output_tokens=500,
    ))

    summary = tracker.summary()
    assert summary["total_calls"] == 1
    assert summary["total_tokens"]["input"] == 1000
    assert summary["total_tokens"]["output"] == 500
    assert summary["total_cost"] > 0


def test_token_tracker_budget():
    tracker = TokenTracker(max_cost_usd=0.001)
    tracker.record(UsageRecord(
        task_type="test", tier="opus", model_id="o",
        input_tokens=100000, output_tokens=50000,
    ))
    assert tracker.would_exceed_budget()


def test_token_tracker_summary_by_tier():
    tracker = TokenTracker(max_cost_usd=100)
    tracker.record(UsageRecord(task_type="a", tier="haiku", model_id="h", input_tokens=100, output_tokens=50))
    tracker.record(UsageRecord(task_type="b", tier="opus", model_id="o", input_tokens=100, output_tokens=50))

    summary = tracker.summary()
    assert "haiku" in summary["by_tier"]
    assert "opus" in summary["by_tier"]
    assert summary["by_tier"]["opus"]["cost"] > summary["by_tier"]["haiku"]["cost"]

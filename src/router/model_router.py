"""Model router: maps task types to the appropriate LLM tier and handles cascade fallback.

Designed with an abstract LLMProvider so non-Anthropic backends (OpenAI, Ollama, vLLM)
can be plugged in later.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from src.router.token_tracker import TokenTracker, UsageRecord

logger = logging.getLogger(__name__)

TIER_ORDER = ["haiku", "sonnet", "opus"]


@dataclass
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int
    model_id: str


class LLMProvider(ABC):
    """Abstract interface for LLM backends."""

    @abstractmethod
    async def call(
        self,
        model_id: str,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int,
    ) -> LLMResponse:
        ...


class AnthropicProvider(LLMProvider):
    """Anthropic Claude provider via the official SDK."""

    def __init__(self, api_key: str):
        import anthropic
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    async def call(
        self,
        model_id: str,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int,
    ) -> LLMResponse:
        response = await self._client.messages.create(
            model=model_id,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
        )
        text = response.content[0].text if response.content else ""
        return LLMResponse(
            text=text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model_id=model_id,
        )


class CascadeExhaustedError(Exception):
    """Raised when all tiers have been tried and validation still fails."""


class BudgetExceededError(Exception):
    """Raised when the token/cost budget has been exceeded."""


class ModelRouter:
    """Routes task types to the appropriate model tier with optional cascade fallback."""

    def __init__(self, config: dict, provider: LLMProvider, tracker: TokenTracker):
        self.tiers = config["tiers"]
        self.routing = config["routing"]
        self.cascade_enabled = config.get("cascade_on_validation_failure", True)
        self.max_cascade = config.get("max_cascade_depth", 2)
        self.provider = provider
        self.tracker = tracker

    def _cascade_order(self, starting_tier: str) -> list[str]:
        """Return the list of tiers to try, starting from the given tier and going up."""
        idx = TIER_ORDER.index(starting_tier)
        tiers = TIER_ORDER[idx : idx + self.max_cascade + 1]
        if not self.cascade_enabled:
            return tiers[:1]
        return tiers

    def _tier_config(self, tier: str) -> dict:
        return self.tiers[tier]

    async def call(
        self,
        task_type: str,
        system: str,
        messages: list[dict[str, str]],
        response_model: type[BaseModel] | None = None,
    ) -> Any:
        """Make an LLM call, routing to the right model with optional cascade on validation failure."""
        starting_tier = self.routing.get(task_type)
        if not starting_tier:
            raise ValueError(f"Unknown task type: {task_type}")

        tiers_to_try = self._cascade_order(starting_tier)
        last_error: Exception | None = None

        for tier in tiers_to_try:
            tier_cfg = self._tier_config(tier)
            model_id = tier_cfg["id"]
            max_tokens = tier_cfg.get("max_tokens", 4096)

            if self.tracker.would_exceed_budget():
                raise BudgetExceededError(
                    f"Budget would be exceeded. Current cost: ${self.tracker.total_cost():.4f}"
                )

            logger.info("LLM call: task=%s tier=%s model=%s", task_type, tier, model_id)

            response = await self.provider.call(
                model_id=model_id,
                system=system,
                messages=messages,
                max_tokens=max_tokens,
            )

            self.tracker.record(
                UsageRecord(
                    task_type=task_type,
                    tier=tier,
                    model_id=model_id,
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                )
            )

            if response_model is not None:
                try:
                    # Try to parse as JSON and validate
                    text = response.text.strip()
                    # Handle markdown code fences
                    if text.startswith("```"):
                        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                    return response_model.model_validate_json(text)
                except (ValidationError, json.JSONDecodeError) as e:
                    last_error = e
                    logger.warning(
                        "Validation failed for tier=%s task=%s: %s. Cascading up.",
                        tier, task_type, e,
                    )
                    continue

            return response.text

        raise CascadeExhaustedError(
            f"All tiers exhausted for task_type={task_type}. Last error: {last_error}"
        )

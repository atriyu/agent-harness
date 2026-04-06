"""Token usage tracking and budget enforcement.

Records every LLM call to a JSONL file for post-run analysis and enforces
configurable cost limits.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Default cost per 1K tokens (overridable via config)
DEFAULT_COSTS = {
    "haiku": {"input": 0.001, "output": 0.005},
    "sonnet": {"input": 0.003, "output": 0.015},
    "opus": {"input": 0.015, "output": 0.075},
}


@dataclass
class UsageRecord:
    task_type: str
    tier: str
    model_id: str
    input_tokens: int
    output_tokens: int
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class TokenTracker:
    """Tracks token usage across the pipeline run and enforces budget limits."""

    max_cost_usd: float = 50.0
    warn_at_pct: float = 80.0
    output_path: Path | None = None
    tier_costs: dict[str, dict[str, float]] = field(default_factory=lambda: dict(DEFAULT_COSTS))

    _records: list[UsageRecord] = field(default_factory=list, init=False)
    _warned: bool = field(default=False, init=False)

    def record(self, usage: UsageRecord) -> None:
        """Record a single LLM call's usage."""
        self._records.append(usage)

        # Append to JSONL file if configured
        if self.output_path:
            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.output_path, "a") as f:
                f.write(json.dumps(asdict(usage)) + "\n")

        # Check warning threshold
        cost = self.total_cost()
        threshold = self.max_cost_usd * (self.warn_at_pct / 100)
        if not self._warned and cost >= threshold:
            self._warned = True
            logger.warning(
                "Token budget warning: $%.4f spent (%.0f%% of $%.2f limit)",
                cost, (cost / self.max_cost_usd) * 100, self.max_cost_usd,
            )

    def _cost_for_record(self, rec: UsageRecord) -> float:
        costs = self.tier_costs.get(rec.tier, DEFAULT_COSTS.get(rec.tier, {"input": 0, "output": 0}))
        return (rec.input_tokens / 1000 * costs["input"]) + (
            rec.output_tokens / 1000 * costs["output"]
        )

    def total_cost(self) -> float:
        return sum(self._cost_for_record(r) for r in self._records)

    def total_tokens(self) -> dict[str, int]:
        total_in = sum(r.input_tokens for r in self._records)
        total_out = sum(r.output_tokens for r in self._records)
        return {"input": total_in, "output": total_out, "total": total_in + total_out}

    def would_exceed_budget(self) -> bool:
        return self.total_cost() >= self.max_cost_usd

    def summary(self) -> dict:
        """Return a summary of usage broken down by task type and tier."""
        by_task: dict[str, dict] = {}
        for rec in self._records:
            key = rec.task_type
            if key not in by_task:
                by_task[key] = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0.0}
            by_task[key]["calls"] += 1
            by_task[key]["input_tokens"] += rec.input_tokens
            by_task[key]["output_tokens"] += rec.output_tokens
            by_task[key]["cost"] += self._cost_for_record(rec)

        by_tier: dict[str, dict] = {}
        for rec in self._records:
            key = rec.tier
            if key not in by_tier:
                by_tier[key] = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0.0}
            by_tier[key]["calls"] += 1
            by_tier[key]["input_tokens"] += rec.input_tokens
            by_tier[key]["output_tokens"] += rec.output_tokens
            by_tier[key]["cost"] += self._cost_for_record(rec)

        return {
            "total_cost": self.total_cost(),
            "total_tokens": self.total_tokens(),
            "total_calls": len(self._records),
            "by_task": by_task,
            "by_tier": by_tier,
            "budget_remaining": self.max_cost_usd - self.total_cost(),
        }

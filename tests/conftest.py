"""Shared test fixtures for the harness self-tests."""

import pytest
from pathlib import Path


@pytest.fixture
def sample_config():
    return {
        "harness": {"output_dir": "/tmp/test-harness-output", "log_level": "DEBUG"},
        "inputs": {"docs_dir": "docs/input", "accepted_formats": ["pdf", "md", "html"]},
        "models": {
            "provider": "anthropic",
            "api_key_env": "ANTHROPIC_API_KEY",
            "tiers": {
                "haiku": {"id": "claude-haiku-4-5-20241022", "max_tokens": 4096,
                          "cost_per_1k_input": 0.001, "cost_per_1k_output": 0.005},
                "sonnet": {"id": "claude-sonnet-4-5-20250929", "max_tokens": 8192,
                           "cost_per_1k_input": 0.003, "cost_per_1k_output": 0.015},
                "opus": {"id": "claude-opus-4-0-20250514", "max_tokens": 16384,
                         "cost_per_1k_input": 0.015, "cost_per_1k_output": 0.075},
            },
            "routing": {
                "document_parsing": "haiku",
                "requirement_extraction": "sonnet",
                "test_plan_generation": "opus",
                "test_code_generation": "sonnet",
                "failure_classification": "haiku",
                "root_cause_analysis": "opus",
                "report_summary": "haiku",
                "test_repair": "sonnet",
            },
            "cascade_on_validation_failure": True,
            "max_cascade_depth": 2,
            "budget": {"max_cost_usd": 10.0, "warn_at_pct": 80},
        },
        "topology": {"provider": "containerlab", "default_topology": "full_stack"},
        "execution": {"timeout_per_test_seconds": 60, "parallel_workers": 1},
        "repair": {"enabled": True, "max_attempts_per_test": 2},
        "reporting": {"formats": ["html", "markdown"]},
    }


@pytest.fixture
def tmp_output_dir(tmp_path):
    output = tmp_path / "generated"
    output.mkdir()
    return output

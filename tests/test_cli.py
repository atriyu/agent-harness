"""Tests for the CLI interface."""

from pathlib import Path

from click.testing import CliRunner

from src.cli import cli


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Agentic QA Harness" in result.output
    assert "run" in result.output
    assert "plan-only" in result.output
    assert "token-usage" in result.output


def test_cli_dry_run(tmp_path):
    """Test dry-run mode validates config without executing."""
    # Create minimal config
    config_path = tmp_path / "harness.yaml"
    config_path.write_text("""
harness:
  output_dir: ./generated
inputs:
  docs_dir: ./docs/input
  accepted_formats: [md]
models:
  api_key_env: ANTHROPIC_API_KEY
  tiers:
    haiku:
      id: claude-haiku-test
    sonnet:
      id: claude-sonnet-test
    opus:
      id: claude-opus-test
  routing:
    document_parsing: haiku
    requirement_extraction: sonnet
    test_plan_generation: opus
  budget:
    max_cost_usd: 10.0
topology:
  topologies_dir: ./config/topologies
""")

    runner = CliRunner()
    result = runner.invoke(cli, ["run", "--config", str(config_path), "--dry-run"])
    assert result.exit_code == 0
    assert "DRY RUN MODE" in result.output
    assert "Config loaded" in result.output
    assert "Pipeline stages" in result.output


def test_cli_token_usage_no_data(tmp_path):
    runner = CliRunner()
    result = runner.invoke(cli, ["token-usage", "--run-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "No token usage data found" in result.output


def test_cli_token_usage_with_data(tmp_path):
    import json

    usage_file = tmp_path / "token_usage.jsonl"
    records = [
        {"task_type": "test", "tier": "haiku", "model_id": "h", "input_tokens": 1000, "output_tokens": 500, "timestamp": "2024-01-01T00:00:00"},
        {"task_type": "test2", "tier": "opus", "model_id": "o", "input_tokens": 2000, "output_tokens": 800, "timestamp": "2024-01-01T00:01:00"},
    ]
    usage_file.write_text("\n".join(json.dumps(r) for r in records))

    runner = CliRunner()
    result = runner.invoke(cli, ["token-usage", "--run-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "Total calls:   2" in result.output
    assert "haiku" in result.output
    assert "opus" in result.output


def test_cli_list_topologies(tmp_path):
    """Test listing topologies."""
    config_path = tmp_path / "harness.yaml"
    topo_dir = tmp_path / "topologies"
    topo_dir.mkdir()
    (topo_dir / "test.clab.yaml").write_text("name: test\n")

    config_path.write_text(f"""
topology:
  topologies_dir: {topo_dir}
""")

    runner = CliRunner()
    result = runner.invoke(cli, ["list-topologies", "--config", str(config_path)])
    assert result.exit_code == 0
    assert "test" in result.output

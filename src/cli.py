"""CLI entry point for the Agentic QA Harness."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

import click

from src.orchestrator.pipeline import Pipeline


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _collect_input_files(pipeline: Pipeline, docs_dir: str | None) -> list[Path]:
    """Collect input document files from the configured directory."""
    input_dir = docs_dir or pipeline.config.get("inputs", {}).get("docs_dir", "docs/input")
    input_path = Path(input_dir)
    if not input_path.exists():
        click.echo(f"Error: docs directory not found: {input_path}", err=True)
        sys.exit(1)

    accepted = pipeline.config.get("inputs", {}).get("accepted_formats", ["pdf", "md", "html"])
    input_files = []
    for fmt in accepted:
        input_files.extend(input_path.glob(f"*.{fmt}"))

    if not input_files:
        click.echo(f"No input documents found in {input_path}", err=True)
        sys.exit(1)

    return sorted(input_files)


@click.group()
@click.option("--log-level", default="INFO", help="Log level (DEBUG, INFO, WARNING, ERROR)")
def cli(log_level: str):
    """Agentic QA Harness for VPN & L4-L7 Networking Products."""
    _setup_logging(log_level)


@cli.command()
@click.option("--config", default="config/harness.yaml", help="Path to harness config")
@click.option("--docs-dir", default=None, help="Override docs input directory")
@click.option("--resume", default=None, help="Resume from checkpoint directory")
@click.option("--dry-run", is_flag=True, help="Validate pipeline flow without LLM calls or execution")
@click.option("--product", default=None, help="Product name for product-specific skills override")
def run(config: str, docs_dir: str | None, resume: str | None, dry_run: bool, product: str | None):
    """Run the full pipeline from documents to report."""
    if dry_run:
        _dry_run(config, docs_dir)
        return

    # Apply product override to config before building pipeline
    if product:
        import yaml
        with open(config) as f:
            cfg = yaml.safe_load(f)
        cfg.setdefault("skills", {})["product"] = product
        # Write temp config
        import tempfile
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
        yaml.dump(cfg, tmp)
        tmp.close()
        config = tmp.name

    pipeline = Pipeline(config_path=config, resume_dir=resume)
    input_files = _collect_input_files(pipeline, docs_dir)

    click.echo(f"Pipeline run_id={pipeline.state.run_id}")
    click.echo(f"Input documents: {len(input_files)}")
    for f in input_files:
        click.echo(f"  - {f.name}")

    state = asyncio.run(pipeline.run([str(f) for f in input_files]))

    # Print summary
    click.echo(f"\nPipeline completed: {state.current_stage.value}")

    summary = pipeline.tracker.summary()
    click.echo(f"Token cost: ${summary['total_cost']:.4f}")
    click.echo(f"LLM calls: {summary['total_calls']}")

    if state.error:
        click.echo(f"Error: {state.error}", err=True)
        sys.exit(1)

    # Print report location
    output_dir = Path(pipeline.config["harness"]["output_dir"])
    report_html = output_dir / "reports" / "report.html"
    if report_html.exists():
        click.echo(f"\nReport: {report_html}")


def _dry_run(config_path: str, docs_dir: str | None):
    """Validate pipeline configuration and document availability without running."""
    import yaml

    click.echo("=== DRY RUN MODE ===\n")

    # Validate config
    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
        click.echo(f"[OK] Config loaded: {config_path}")
    except Exception as e:
        click.echo(f"[FAIL] Config: {e}", err=True)
        sys.exit(1)

    # Check docs directory
    input_dir = docs_dir or config.get("inputs", {}).get("docs_dir", "docs/input")
    input_path = Path(input_dir)
    if input_path.exists():
        accepted = config.get("inputs", {}).get("accepted_formats", ["pdf", "md", "html"])
        files = []
        for fmt in accepted:
            files.extend(input_path.glob(f"*.{fmt}"))
        click.echo(f"[OK] Input docs: {len(files)} files in {input_path}")
        for f in files:
            click.echo(f"     - {f.name} ({f.stat().st_size:,} bytes)")
    else:
        click.echo(f"[WARN] Docs dir not found: {input_path}")

    # Check model config
    models = config.get("models", {})
    click.echo(f"\n[INFO] Model routing:")
    for task, tier in models.get("routing", {}).items():
        model_id = models.get("tiers", {}).get(tier, {}).get("id", "?")
        click.echo(f"  {task:30s} -> {tier:8s} ({model_id})")

    budget = models.get("budget", {})
    click.echo(f"\n[INFO] Budget: ${budget.get('max_cost_usd', 'N/A')}")

    # Check API key
    import os
    api_key_env = models.get("api_key_env", "ANTHROPIC_API_KEY")
    has_key = bool(os.environ.get(api_key_env))
    click.echo(f"[{'OK' if has_key else 'WARN'}] API key ({api_key_env}): {'set' if has_key else 'NOT SET'}")

    # Check topology config
    topo = config.get("topology", {})
    topo_dir = Path(topo.get("topologies_dir", "config/topologies"))
    if topo_dir.exists():
        topos = list(topo_dir.glob("*.clab.*"))
        click.echo(f"\n[OK] Topologies: {len(topos)} in {topo_dir}")
        for t in topos:
            click.echo(f"     - {t.stem}")
    else:
        click.echo(f"\n[WARN] Topology dir not found: {topo_dir}")

    # Check containerlab
    import subprocess
    try:
        result = subprocess.run(["containerlab", "version"], capture_output=True, text=True, timeout=5)
        click.echo(f"[OK] Containerlab: {result.stdout.strip().split(chr(10))[0]}")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        click.echo("[WARN] Containerlab: not found (install for topology deployment)")

    # Pipeline stages
    from src.orchestrator.state import STAGE_ORDER
    click.echo(f"\n[INFO] Pipeline stages: {' -> '.join(s.value for s in STAGE_ORDER)}")

    # Output dir
    output_dir = Path(config.get("harness", {}).get("output_dir", "generated"))
    click.echo(f"[INFO] Output directory: {output_dir}")

    click.echo("\n=== DRY RUN COMPLETE (no LLM calls or tests executed) ===")


@cli.command("plan-only")
@click.option("--config", default="config/harness.yaml")
@click.option("--docs-dir", default=None)
def plan_only(config: str, docs_dir: str | None):
    """Run only through test plan generation (ingest -> extract -> plan)."""
    pipeline = Pipeline(config_path=config)
    input_files = _collect_input_files(pipeline, docs_dir)

    click.echo(f"Plan-only mode: run_id={pipeline.state.run_id}")
    click.echo(f"Input documents: {len(input_files)}")

    # Override stage order to stop after PLAN
    from src.orchestrator.state import PipelineStage

    async def run_plan_only():
        from src.orchestrator.state import (
            is_stage_completed,
            mark_stage_completed,
            mark_stage_failed,
            save_pipeline_state,
        )
        import time

        stages = [PipelineStage.INGEST, PipelineStage.EXTRACT, PipelineStage.PLAN]

        for stage in stages:
            if is_stage_completed(pipeline.state, stage):
                continue

            pipeline.state.current_stage = stage
            agent = pipeline._get_agent(stage)
            click.echo(f"\nRunning stage: {stage.value}...")
            start = time.time()

            try:
                result = await agent.run(pipeline._stage_inputs(stage))
                duration = time.time() - start
                artifact_paths = result.get("artifact_paths", []) if isinstance(result, dict) else []
                mark_stage_completed(pipeline.state, stage, artifact_paths, duration)
                save_pipeline_state(pipeline.state, pipeline.output_dir)
                click.echo(f"  Completed in {duration:.1f}s")
            except Exception as e:
                mark_stage_failed(pipeline.state, stage, str(e))
                save_pipeline_state(pipeline.state, pipeline.output_dir)
                click.echo(f"  Failed: {e}", err=True)
                sys.exit(1)

        return pipeline.state

    state = asyncio.run(run_plan_only())

    summary = pipeline.tracker.summary()
    click.echo(f"\nPlan generation complete. Cost: ${summary['total_cost']:.4f}")
    click.echo(f"Test plan saved to: {pipeline.output_dir / 'test_plans'}")


@cli.command("execute-only")
@click.argument("test_dir")
@click.option("--config", default="config/harness.yaml")
@click.option("--topology", default=None, help="Topology to deploy before running")
def execute_only(test_dir: str, config: str, topology: str | None):
    """Execute pre-generated tests without re-generating."""
    import os
    import subprocess

    test_path = Path(test_dir)
    if not test_path.exists():
        click.echo(f"Test directory not found: {test_path}", err=True)
        sys.exit(1)

    test_files = list(test_path.glob("test_*.py"))
    if not test_files:
        click.echo(f"No test files found in {test_path}", err=True)
        sys.exit(1)

    click.echo(f"Executing {len(test_files)} test files from {test_path}")

    # Set topology env vars if specified
    env = os.environ.copy()
    if topology:
        env["HARNESS_TOPOLOGY"] = topology
        env["HARNESS_DEPLOY_TOPOLOGY"] = "1"

    cmd = [
        sys.executable, "-m", "pytest",
        str(test_path), "-v", "--tb=long",
        "--json-report", f"--json-report-file={test_path / 'results.json'}",
    ]

    click.echo(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, env=env)
    sys.exit(result.returncode)


@cli.command("triage-only")
@click.argument("results_path")
@click.option("--config", default="config/harness.yaml")
def triage_only(results_path: str, config: str):
    """Run triage on existing test results."""
    results_file = Path(results_path)
    if not results_file.exists():
        click.echo(f"Results not found: {results_file}", err=True)
        sys.exit(1)

    pipeline = Pipeline(config_path=config)

    # Copy results to expected location
    from src.artifacts.models import TestRunResult
    run_result = TestRunResult.model_validate_json(results_file.read_text())
    pipeline.store.save("results", results_file.name, run_result)

    click.echo(f"Triaging {run_result.failed + run_result.errored} failures from run {run_result.run_id}")

    async def run_triage():
        from src.orchestrator.state import PipelineStage
        agent = pipeline._get_agent(PipelineStage.TRIAGE)
        return await agent.run(pipeline._stage_inputs(PipelineStage.TRIAGE))

    result = asyncio.run(run_triage())

    triage = result.get("triage_report")
    if triage:
        click.echo(f"\nTriage complete: {len(triage.entries)} failure clusters")
        for entry in triage.entries:
            click.echo(
                f"  [{entry.severity.value:8s}] {entry.root_cause_category.value:15s} "
                f"| {entry.root_cause_description[:60]}"
            )
        click.echo(f"\nSummary: {triage.summary}")

    summary = pipeline.tracker.summary()
    click.echo(f"\nCost: ${summary['total_cost']:.4f}")


@cli.command("token-usage")
@click.option("--run-dir", default="generated", help="Pipeline output directory")
def token_usage(run_dir: str):
    """Display token usage and cost summary from the last run."""
    usage_file = Path(run_dir) / "token_usage.jsonl"
    if not usage_file.exists():
        click.echo("No token usage data found.")
        return

    from src.router.token_tracker import TokenTracker, UsageRecord

    tracker = TokenTracker()
    for line in usage_file.read_text().strip().split("\n"):
        if not line:
            continue
        rec_data = json.loads(line)
        tracker.record(UsageRecord(**rec_data))

    summary = tracker.summary()

    click.echo("=== Token Usage Summary ===\n")
    click.echo(f"Total cost:    ${summary['total_cost']:.4f}")
    click.echo(f"Total calls:   {summary['total_calls']}")
    tokens = summary["total_tokens"]
    click.echo(f"Input tokens:  {tokens['input']:,}")
    click.echo(f"Output tokens: {tokens['output']:,}")
    click.echo(f"Total tokens:  {tokens['total']:,}")

    if summary["by_tier"]:
        click.echo("\nBy model tier:")
        click.echo(f"  {'Tier':10s} {'Calls':>6s} {'Input':>10s} {'Output':>10s} {'Cost':>10s}")
        click.echo(f"  {'-'*48}")
        for tier, data in sorted(summary["by_tier"].items()):
            click.echo(
                f"  {tier:10s} {data['calls']:6d} "
                f"{data['input_tokens']:10,} {data['output_tokens']:10,} "
                f"${data['cost']:9.4f}"
            )

    if summary["by_task"]:
        click.echo("\nBy task type:")
        click.echo(f"  {'Task':30s} {'Calls':>6s} {'Cost':>10s}")
        click.echo(f"  {'-'*48}")
        for task, data in sorted(summary["by_task"].items()):
            click.echo(f"  {task:30s} {data['calls']:6d} ${data['cost']:9.4f}")


@cli.command("list-topologies")
@click.option("--config", default="config/harness.yaml")
def list_topologies(config: str):
    """List available Containerlab topologies."""
    import yaml

    with open(config) as f:
        cfg = yaml.safe_load(f)

    topo_dir = Path(cfg.get("topology", {}).get("topologies_dir", "config/topologies"))
    if not topo_dir.exists():
        click.echo(f"Topology directory not found: {topo_dir}")
        return

    from src.topology.manager import TopologyManager
    manager = TopologyManager(topo_dir)

    click.echo(f"Available topologies in {topo_dir}:\n")
    for name in manager.list_topologies():
        topo_file = manager.get_topology_file(name)
        size = topo_file.stat().st_size
        click.echo(f"  {name:20s} ({size:,} bytes)")


if __name__ == "__main__":
    cli()

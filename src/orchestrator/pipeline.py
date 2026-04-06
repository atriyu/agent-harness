"""Main pipeline orchestrator: DAG executor with checkpointing.

Coordinates all agents through the pipeline stages, manages state transitions,
and supports resume from checkpoint after failures.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import yaml

from src.artifacts.models import PipelineStage, PipelineState
from src.artifacts.store import ArtifactStore
from src.orchestrator.state import (
    STAGE_ORDER,
    is_stage_completed,
    load_pipeline_state,
    mark_stage_completed,
    mark_stage_failed,
    new_pipeline_state,
    save_pipeline_state,
)
from src.router.model_router import (
    AnthropicProvider,
    BudgetExceededError,
    ModelRouter,
)
from src.router.token_tracker import TokenTracker

logger = logging.getLogger(__name__)


def _load_config(config_path: str) -> dict:
    with open(config_path) as f:
        return yaml.safe_load(f)


def _build_router(config: dict) -> tuple[ModelRouter, TokenTracker]:
    """Build the model router and token tracker from config."""
    models_cfg = config["models"]
    budget_cfg = models_cfg.get("budget", {})

    api_key = os.environ.get(models_cfg.get("api_key_env", "ANTHROPIC_API_KEY"), "")
    provider = AnthropicProvider(api_key=api_key)

    tracker = TokenTracker(
        max_cost_usd=budget_cfg.get("max_cost_usd", 50.0),
        warn_at_pct=budget_cfg.get("warn_at_pct", 80.0),
        output_path=Path(config["harness"]["output_dir"]) / "token_usage.jsonl",
    )

    # Build tier costs from config
    for tier_name, tier_cfg in models_cfg.get("tiers", {}).items():
        if "cost_per_1k_input" in tier_cfg:
            tracker.tier_costs[tier_name] = {
                "input": tier_cfg["cost_per_1k_input"],
                "output": tier_cfg["cost_per_1k_output"],
            }

    router = ModelRouter(config=models_cfg, provider=provider, tracker=tracker)
    return router, tracker


def _build_skill_registry(config: dict):
    """Build the skill registry from config, with optional API skill generation."""
    skills_cfg = config.get("skills", {})
    skills_dir = skills_cfg.get("skills_dir", "skills")
    product = skills_cfg.get("product")

    if not Path(skills_dir).exists():
        logger.info("Skills directory not found: %s. Running without skills.", skills_dir)
        return None

    from src.skills.registry import SkillRegistry

    # Auto-generate API reference skills if configured
    if skills_cfg.get("auto_generate_api_skills", True):
        try:
            from src.skills.generator import generate_all_api_skills
            api_dir = Path(skills_dir) / "api-reference"
            generate_all_api_skills("src/networking", str(api_dir))
        except Exception as e:
            logger.warning("Failed to auto-generate API skills: %s", e)

    registry = SkillRegistry(skills_dir, product=product)
    logger.info(
        "Skill registry loaded: %d skills (product=%s)",
        len(registry.all_skills), product or "none",
    )
    return registry


class Pipeline:
    """Executes the full QA pipeline from document ingestion to report generation."""

    def __init__(self, config_path: str, resume_dir: str | None = None):
        self.config_path = config_path
        self.config = _load_config(config_path)
        self.output_dir = Path(self.config["harness"]["output_dir"])
        self.store = ArtifactStore(self.output_dir)
        self.router, self.tracker = _build_router(self.config)
        self.skill_registry = _build_skill_registry(self.config)

        if resume_dir:
            self.state = load_pipeline_state(Path(resume_dir))
            logger.info("Resumed pipeline run_id=%s from %s", self.state.run_id, resume_dir)
        else:
            self.state = new_pipeline_state(config_path)
            logger.info("New pipeline run_id=%s", self.state.run_id)

    def _get_agent(self, stage: PipelineStage):
        """Lazy-import and instantiate the agent for a given stage."""
        agent_config = self.config
        common_args = (self.router, self.store, agent_config, self.skill_registry)

        if stage == PipelineStage.INGEST:
            from src.agents.ingest import IngestAgent
            return IngestAgent(*common_args)
        elif stage == PipelineStage.EXTRACT:
            from src.agents.extract import ExtractAgent
            return ExtractAgent(*common_args)
        elif stage == PipelineStage.PLAN:
            from src.agents.plan import PlanAgent
            return PlanAgent(*common_args)
        elif stage == PipelineStage.GAP_ANALYSIS:
            from src.agents.gap_analysis import GapAnalysisAgent
            return GapAnalysisAgent(*common_args)
        elif stage == PipelineStage.API_ENHANCE:
            from src.agents.api_enhance import APIEnhanceAgent
            return APIEnhanceAgent(*common_args)
        elif stage == PipelineStage.CODEGEN:
            from src.agents.codegen import CodeGenAgent
            return CodeGenAgent(*common_args)
        elif stage == PipelineStage.EXECUTE:
            from src.agents.executor import ExecutorAgent
            return ExecutorAgent(*common_args)
        elif stage == PipelineStage.TRIAGE:
            from src.agents.triage import TriageAgent
            return TriageAgent(*common_args)
        elif stage == PipelineStage.REPORT:
            from src.agents.report import ReportAgent
            return ReportAgent(*common_args)
        else:
            raise ValueError(f"No agent for stage: {stage}")

    def _stage_inputs(self, stage: PipelineStage) -> dict:
        """Gather the inputs needed for a stage from previously completed stages."""
        return {
            "stage": stage.value,
            "store": self.store,
            "config": self.config,
            "state": self.state,
            "output_dir": self.output_dir,
        }

    async def run(self, input_paths: list[str] | None = None) -> PipelineState:
        """Execute the full pipeline, resuming from the last checkpoint if applicable."""
        # Store input paths for the ingest stage
        if input_paths:
            self.store.save_text("ingest", "input_paths.json", str(input_paths))

        for stage in STAGE_ORDER:
            if is_stage_completed(self.state, stage):
                logger.info("Skipping completed stage: %s", stage.value)
                continue

            self.state.current_stage = stage
            logger.info("=== Starting stage: %s ===", stage.value)

            agent = self._get_agent(stage)
            start_time = time.time()

            try:
                result = await agent.run(self._stage_inputs(stage))
                duration = time.time() - start_time

                artifact_paths = []
                if isinstance(result, dict) and "artifact_paths" in result:
                    artifact_paths = result["artifact_paths"]

                mark_stage_completed(self.state, stage, artifact_paths, duration)
                save_pipeline_state(self.state, self.output_dir)

                logger.info(
                    "Stage %s completed in %.1fs", stage.value, duration
                )

            except BudgetExceededError as e:
                duration = time.time() - start_time
                mark_stage_failed(self.state, stage, str(e), duration)
                save_pipeline_state(self.state, self.output_dir)
                logger.error("Budget exceeded at stage %s: %s", stage.value, e)
                raise

            except Exception as e:
                duration = time.time() - start_time
                mark_stage_failed(self.state, stage, str(e), duration)
                save_pipeline_state(self.state, self.output_dir)
                logger.error("Stage %s failed: %s", stage.value, e, exc_info=True)
                raise

        self.state.current_stage = PipelineStage.COMPLETE
        save_pipeline_state(self.state, self.output_dir)

        # Log token usage summary
        summary = self.tracker.summary()
        logger.info(
            "Pipeline complete. Total cost: $%.4f | Tokens: %s | Calls: %d",
            summary["total_cost"],
            summary["total_tokens"],
            summary["total_calls"],
        )

        return self.state
